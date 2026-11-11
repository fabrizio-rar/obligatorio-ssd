"""Runs the eval cases against the real model, through the SAME code path as POST /api/chat
(agent/service.py::chat_turn), and records what happened in every turn."""

import asyncio
import time
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.agent.llm.base import LLMError, LLMProvider
from app.agent.service import chat_turn
from app.auth import service as auth
from app.config import Settings
from app.domain import cart
from app.domain.checkout import CheckoutRequest, ShippingPolicy, confirm_order, create_checkout
from app.domain.errors import DomainError
from app.evals.cases import Case
from app.evals.checks import CheckResult, ProductFacts, ToolCallObs, TurnObservation, evaluate
from app.models import (
    Category,
    ChatMessage,
    Order,
    Price,
    Product,
    Subcategory,
    ToolCallLog,
    User,
)
from app.models.catalog import product_availability
from app.retrieval.embeddings import Embedder

EVAL_USER_PREFIX = "eval_"


@dataclass
class TurnRecord:
    user: str
    message: str
    type: str
    tools: list[dict]
    checks: list[dict]
    passed: bool
    latency_ms: int
    steps: int
    input_tokens: int
    output_tokens: int
    stop_reason: str
    error: str | None = None


@dataclass
class RunRecord:
    """One run (one repetition) of one case."""

    case_id: str
    category: str
    repetition: int
    passed: bool
    turns: list[TurnRecord] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _resolve(session: Session, ref: str) -> str:
    """A product name (unique in the dataset) or a product ID."""
    if session.get(Product, ref):
        return ref
    ids = session.scalars(select(Product.id).where(Product.name == ref)).all()
    if len(ids) != 1:
        raise ValueError(f"product {ref!r}: {len(ids)} matches, use its ID")
    return ids[0]


def _prepare(session: Session, case: Case, policy: ShippingPolicy) -> int:
    user = auth.register(session, f"{EVAL_USER_PREFIX}{uuid.uuid4().hex[:12]}", "eval-secret")
    for ref, quantity in case.setup.purchases:
        cart.add_item(session, user.id, _resolve(session, ref), quantity)
        request = CheckoutRequest(
            customer_name="Eval",
            email="eval@example.com",
            delivery_method="SHIPPING",
            shipping_address={
                "street": "Eval 123",
                "city": "Montevideo",
                "department": "Montevideo",
            },
            payment_method="CARD",
        )
        order = create_checkout(session, user.id, request, policy)
        confirm_order(session, user.id, order.order_id, policy)
    for ref, quantity in case.setup.cart:
        cart.add_item(session, user.id, _resolve(session, ref), quantity)
    return user.id


def _facts(session: Session, ids: list[str]) -> dict[str, ProductFacts]:
    if not ids:
        return {}
    rows = session.execute(
        select(Product, Category.name, Price.current_price, product_availability.c.available)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .join(Price, Price.product_id == Product.id)
        .join(product_availability, product_availability.c.product_id == Product.id)
        .where(Product.id.in_(ids))
    )
    return {
        p.id: ProductFacts(p.id, p.name, category, float(price), p.active, available or 0)
        for p, category, price, available in rows
    }


def _tools(session: Session, conversation_id: uuid.UUID) -> list[ToolCallObs]:
    message_id = session.scalar(
        select(ChatMessage.id)
        .where(ChatMessage.conversation_id == conversation_id, ChatMessage.role == "assistant")
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    logs = session.scalars(
        select(ToolCallLog)
        .where(ToolCallLog.message_id == message_id)
        .order_by(ToolCallLog.step, ToolCallLog.id)
    )
    return [
        ToolCallObs(
            log.tool_name,
            log.arguments,
            ((log.result or {}).get("error") or {}).get("code") if log.is_error else None,
        )
        for log in logs
    ]


def _orders(session: Session, user_id: int) -> int:
    return (
        session.scalar(select(func.count()).select_from(Order).where(Order.user_id == user_id)) or 0
    )


async def run_case(
    case: Case,
    repetition: int,
    factory: sessionmaker[Session],
    llm: LLMProvider,
    embedder: Embedder | None,
    settings: Settings,
) -> RunRecord:
    policy = ShippingPolicy(settings.shipping_cost_usd, settings.free_shipping_from_usd)
    run = RunRecord(case.id, case.category, repetition, passed=False)
    with factory() as session:
        try:
            user_id = _prepare(session, case, policy)
        except (DomainError, ValueError) as error:
            run.error = f"setup: {error}"
            return run
        orders_before = _orders(session, user_id)
        conversation_id = None
        for turn in case.turns:
            started = time.monotonic()
            try:
                chat = await chat_turn(
                    session, llm, embedder, settings, turn.user, conversation_id, user_id=user_id
                )
            except (LLMError, DomainError) as error:
                elapsed = int((time.monotonic() - started) * 1000)
                run.turns.append(
                    TurnRecord(
                        turn.user, "", "", [], [], False, elapsed, 0, 0, 0, "error", str(error)
                    )
                )
                break
            conversation_id = chat.conversation_id
            session.expire_all()
            response = chat.response.model_dump(mode="json")
            tools = _tools(session, conversation_id)
            obs = TurnObservation(
                response=response,
                tools=tools,
                products=_facts(session, response.get("product_ids") or []),
                cart={i.name: i.quantity for i in cart.get_cart(session, user_id).items},
                orders_created=_orders(session, user_id) - orders_before,
                stop_reason=chat.meta.stop_reason,
            )
            checks: list[CheckResult] = evaluate(turn.expect, obs)
            run.turns.append(
                TurnRecord(
                    user=turn.user,
                    message=response.get("message", ""),
                    type=response.get("type", ""),
                    tools=[
                        {"name": t.name, "arguments": t.arguments, "error": t.error_code}
                        for t in tools
                    ],
                    checks=[asdict(c) for c in checks],
                    passed=all(c.ok for c in checks),
                    latency_ms=chat.meta.latency_ms,
                    steps=chat.meta.steps,
                    input_tokens=chat.meta.input_tokens,
                    output_tokens=chat.meta.output_tokens,
                    stop_reason=chat.meta.stop_reason,
                )
            )
        run.passed = (
            run.error is None
            and len(run.turns) == len(case.turns)
            and all(t.passed and t.error is None for t in run.turns)
        )
    return run


async def run_all(
    cases: list[Case],
    repeat: int,
    factory: sessionmaker[Session],
    llm: LLMProvider,
    embedder: Embedder | None,
    settings: Settings,
    concurrency: int,
    on_done=None,
) -> list[RunRecord]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(case: Case, rep: int) -> RunRecord:
        async with semaphore:
            record = await run_case(case, rep, factory, llm, embedder, settings)
            if on_done:
                on_done(record)
            return record

    jobs = [one(c, r) for c in cases for r in range(1, repeat + 1)]
    return list(await asyncio.gather(*jobs))


def delete_eval_users(factory: sessionmaker[Session]) -> int:
    """Their carts, conversations and orders go with them (ON DELETE CASCADE). The stock their
    setup purchases took is not returned: `scripts.ingest --reset` restores the dataset."""
    with factory() as session:
        result = session.execute(delete(User).where(User.username.like(f"{EVAL_USER_PREFIX}%")))
        session.commit()
        return result.rowcount or 0


def cost_usd(input_tokens: int, output_tokens: int, settings: Settings) -> Decimal:
    return (
        Decimal(input_tokens) * Decimal(str(settings.llm_usd_per_1m_input))
        + Decimal(output_tokens) * Decimal(str(settings.llm_usd_per_1m_output))
    ) / Decimal(1_000_000)
