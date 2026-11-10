"""Order tools of the agent (get_orders, get_order, start_checkout) with FakeLLM.
None of them buys: the purchase is only the checkout's button (AGENTS.md rule 2)."""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeLLM, final, tool_call
from app.agent.loop import TurnLimits, run_turn
from app.agent.state import AgentState
from app.agent.tools import ToolContext
from app.auth import service as auth
from app.domain import cart
from app.domain.checkout import (
    CheckoutRequest,
    DeliveryMethod,
    ShippingPolicy,
    confirm_order,
    create_checkout,
    prepare_checkout,
)
from app.domain.errors import DomainError
from app.models import Inventory, Order, Product
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)
LIMITS = TurnLimits(max_steps=6, timeout_seconds=30, max_tokens=100_000)
POLICY = ShippingPolicy(cost=Decimal("8.00"), free_from=Decimal("200.00"))


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    return catalog_db


@pytest.fixture
def user_id(db) -> int:
    return auth.register(db, f"ord{uuid.uuid4().hex[:8]}", "secret123").id


def _id(db, name):
    return db.scalar(select(Product.id).where(Product.name == name))


def _answer(type_="info", product_ids=()) -> dict:
    return {
        "type": type_,
        "message": "ok",
        "product_ids": list(product_ids),
        "clarifying_question": None,
        "suggested_replies": [],
    }


def _run(db, user_id, steps):
    ctx = ToolContext(db, EMBEDDER, user_id=user_id)
    return asyncio.run(run_turn(FakeLLM(steps), ctx, LIMITS, [], "...", AgentState()))


def _buy(db, user_id, product_id) -> str:
    cart.add_item(db, user_id, product_id, 1)
    request = CheckoutRequest(
        customer_name="Ana Pérez",
        email="ana@example.com",
        delivery_method="SHIPPING",
        shipping_address={
            "street": "18 de Julio 1234",
            "city": "Montevideo",
            "department": "Montevideo",
        },
        payment_method="CARD",
    )
    order = create_checkout(db, user_id, request, POLICY)
    return confirm_order(db, user_id, order.order_id, POLICY).code


def _start(delivery_method=None, warehouse=None):
    return tool_call(
        "start_checkout", {"delivery_method": delivery_method, "pickup_warehouse_id": warehouse}
    )


def _snapshot(db):
    db.expire_all()
    return (
        db.scalar(select(func.count()).select_from(Order)),
        db.scalar(select(func.sum(Inventory.on_hand_qty))),
    )


# --- get_orders / get_order ----------------------------------------------------------------------


def test_get_orders_lists_the_purchases(db, user_id):
    vector = _id(db, "Vector Air 690")
    code = _buy(db, user_id, vector)
    turn = _run(db, user_id, [tool_call("get_orders", {"limit": None}), final(_answer())])
    result = turn.tool_executions[0][1].result
    assert result["total_orders"] == 1
    order = result["orders"][0]
    assert order["code"] == code and order["products"] == ["Vector Air 690"]
    assert order["total"].startswith("USD ") and order["delivery"] == "home delivery"


def test_get_orders_without_purchases(db, user_id):
    turn = _run(db, user_id, [tool_call("get_orders", {"limit": 3}), final(_answer())])
    assert turn.tool_executions[0][1].result == {"ok": True, "total_orders": 0, "orders": []}


def test_get_order_detail_and_cards_to_buy_again(db, user_id):
    vector = _id(db, "Vector Air 690")
    code = _buy(db, user_id, vector)
    turn = _run(
        db,
        user_id,
        [
            tool_call("get_order", {"order_code": code.lower()}),  # the user may type it lowercase
            final(_answer(product_ids=[vector])),
        ],
    )
    execution = turn.tool_executions[0][1]
    item = execution.result["order"]["items"][0]
    assert item["name"] == "Vector Air 690" and item["shipped_from"]
    assert execution.product_ids == [vector]  # still for sale: it can be a card
    assert turn.response.product_ids == [vector]


def test_someone_elses_order_is_not_found(db, user_id):
    code = _buy(db, user_id, _id(db, "Vector Air 690"))
    other = auth.register(db, f"ord{uuid.uuid4().hex[:8]}", "secret123").id
    turn = _run(db, other, [tool_call("get_order", {"order_code": code}), final(_answer())])
    assert turn.tool_executions[0][1].result["error"]["code"] == "ORDER_NOT_FOUND"


# --- start_checkout ----------------------------------------------------------------------------


def test_start_checkout_hands_off_and_buys_nothing(db, user_id):
    cart.add_item(db, user_id, _id(db, "Vector Air 690"), 1)
    before = _snapshot(db)
    turn = _run(db, user_id, [_start(), final(_answer(type_="checkout"))])

    execution = turn.tool_executions[0][1]
    assert execution.result["checkout_ready"] is True
    assert "NOTHING was bought" in execution.result["note"]
    handoff = turn.response.checkout  # filled by the backend, not by the model
    assert handoff is not None and handoff.delivery_method is None
    assert handoff.shipping_cost == Decimal("8.00")  # 74.45 < 200
    assert _snapshot(db) == before  # no order, no stock change
    assert cart.get_cart(db, user_id).item_count == 1


def test_start_checkout_with_a_branch_that_has_everything(db, user_id):
    vector = _id(db, "Vector Air 690")
    cart.add_item(db, user_id, vector, 1)
    branch = db.scalar(
        select(Inventory.warehouse_id)
        .where(Inventory.product_id == vector)
        .order_by(Inventory.available_qty.desc())
    )
    turn = _run(db, user_id, [_start(None, branch), final(_answer(type_="checkout"))])
    handoff = turn.response.checkout
    assert handoff.delivery_method == DeliveryMethod.PICKUP  # a branch implies pickup
    assert handoff.pickup_warehouse.warehouse_id == branch
    assert handoff.shipping_cost == Decimal("0.00")


def test_branch_without_stock_goes_back_to_the_model_with_alternatives(db, user_id):
    cart.add_item(db, user_id, _id(db, "Vector Air 690"), 1)  # Colonia has 0 in the dataset
    turn = _run(db, user_id, [_start("PICKUP", "WH-COL-001"), final(_answer())])
    error = turn.tool_executions[0][1].result["error"]
    assert error["code"] == "PICKUP_UNAVAILABLE"
    assert error["details"]["warehouses_that_can"] and error["details"]["suggestion"] == "SHIPPING"
    assert turn.response.checkout is None  # no button when it failed


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        ({"delivery_method": "PICKUP", "pickup_warehouse_id": "WH-XXX-000"}, "INVALID_INPUT"),
        ({"delivery_method": "DRONE", "pickup_warehouse_id": None}, "INVALID_ARGUMENTS"),
    ],
)
def test_invalid_checkout_arguments(db, user_id, arguments, code):
    cart.add_item(db, user_id, _id(db, "Vector Air 690"), 1)
    turn = _run(db, user_id, [tool_call("start_checkout", arguments), final(_answer())])
    assert turn.tool_executions[0][1].result["error"]["code"] == code
    assert turn.response.checkout is None


def test_empty_cart_cannot_go_to_checkout(db, user_id):
    turn = _run(db, user_id, [_start(), final(_answer())])
    assert turn.tool_executions[0][1].result["error"]["code"] == "EMPTY_CART"


def test_no_checkout_button_if_the_turn_falls_back(db, user_id):
    cart.add_item(db, user_id, _id(db, "Vector Air 690"), 1)
    turn = _run(db, user_id, [_start(), final("not json"), final("still not json")])
    assert turn.stop_reason == "format"
    assert turn.response.checkout is None


def test_prepare_checkout_domain_rules(db, user_id):
    with pytest.raises(DomainError) as info:
        prepare_checkout(db, user_id, None, None, POLICY)
    assert info.value.code == "EMPTY_CART"
    cart.add_item(db, user_id, _id(db, "Lumina Sound 757"), 2)  # 330.14 >= 200
    handoff = prepare_checkout(db, user_id, DeliveryMethod.SHIPPING, None, POLICY)
    assert handoff.shipping_cost == Decimal("0.00") and handoff.total == handoff.subtotal
