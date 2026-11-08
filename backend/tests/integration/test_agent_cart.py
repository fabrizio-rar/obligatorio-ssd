"""Cart tools of the agent (levels 1, 2 and 3 of docs/PLAN.md §10.4.1) with FakeLLM."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMResult, ToolCall, Usage
from app.agent.llm.fake import FakeLLM, final, tool_call
from app.agent.loop import TurnLimits, run_turn
from app.agent.state import AgentState
from app.agent.tools import ToolContext
from app.api.chat import get_llm, get_query_embedder
from app.auth import service as auth
from app.domain import cart
from app.main import app
from app.models import Product
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)
LIMITS = TurnLimits(max_steps=6, timeout_seconds=30, max_tokens=100_000)


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    return catalog_db


@pytest.fixture
def user_id(db) -> int:
    return auth.register(db, f"cart{uuid.uuid4().hex[:8]}", "secret123").id


def _id(db, name):
    return db.scalar(select(Product.id).where(Product.name == name))


def _answer(type_="cart_update", message="Listo", product_ids=()) -> dict:
    return {
        "type": type_,
        "message": message,
        "product_ids": list(product_ids),
        "clarifying_question": None,
        "suggested_replies": [],
    }


def _run(db, user_id, steps, seen=(), limits=LIMITS):
    llm = FakeLLM(steps)
    ctx = ToolContext(db, EMBEDDER, user_id=user_id)
    state = AgentState(seen_product_ids=list(seen))
    return asyncio.run(run_turn(llm, ctx, limits, [], "...", state)), llm


def _quantities(db, user_id) -> dict[str, int]:
    return {i.product_id: i.quantity for i in cart.get_cart(db, user_id).items}


# --- Level 1 and 2 ------------------------------------------------------------------------------


def test_add_after_looking_the_product_up(db, user_id):
    pid = _id(db, "Vector Air 690")
    turn, _ = _run(
        db,
        user_id,
        [
            tool_call("get_product", {"name": "Vector Air 690", "product_id": None}),
            tool_call("add_to_cart", {"product_id": pid, "quantity": 2}, call_id="c2"),
            final(_answer(product_ids=[pid])),
        ],
    )
    assert _quantities(db, user_id) == {pid: 2}
    assert turn.response.ui_actions == ["refresh_cart"]  # filled by the backend
    assert turn.response.type == "cart_update"
    result = turn.tool_executions[1][1].result
    assert result["action"] == "added" and result["cart"]["item_count"] == 2


def test_add_rejects_an_id_no_tool_returned(db, user_id):
    real_but_unseen = _id(db, "Orbit Sound 458")
    turn, _ = _run(
        db,
        user_id,
        [
            tool_call("add_to_cart", {"product_id": real_but_unseen, "quantity": 1}),
            final(_answer(type_="clarification")),
        ],
    )
    error = turn.tool_executions[0][1].result["error"]
    assert error["code"] == "UNKNOWN_PRODUCT_REFERENCE"
    assert _quantities(db, user_id) == {}
    assert turn.response.ui_actions == []


def test_domain_errors_go_back_to_the_model(db, user_id):
    no_stock = _id(db, "Nimbus Sound 691")
    turn, llm = _run(
        db,
        user_id,
        [tool_call("add_to_cart", {"product_id": no_stock, "quantity": 1}), final(_answer())],
        seen=[no_stock],
    )
    sent = json.loads(llm.requests[1]["tool_outputs"][0].output)
    assert sent["error"]["code"] == "OUT_OF_STOCK"
    assert turn.response.ui_actions == []


def test_quantity_limits_are_enforced_by_the_domain(db, user_id):
    pid = _id(db, "Vector Air 690")
    turn, _ = _run(
        db,
        user_id,
        [tool_call("add_to_cart", {"product_id": pid, "quantity": 50}), final(_answer())],
        seen=[pid],
    )
    assert turn.tool_executions[0][1].result["error"]["code"] == "INVALID_INPUT"
    assert _quantities(db, user_id) == {}


def test_update_an_item_already_in_the_cart(db, user_id):
    pid = _id(db, "Vector Air 690")
    cart.add_item(db, user_id, pid, 1)  # added from the UI: not "seen" in this conversation
    turn, _ = _run(
        db,
        user_id,
        [tool_call("update_cart_item", {"product_id": pid, "quantity": 3}), final(_answer())],
    )
    assert _quantities(db, user_id) == {pid: 3}
    assert turn.response.ui_actions == ["refresh_cart"]


def test_get_cart_reads_only_the_users_cart(db, user_id):
    pid = _id(db, "Vector Air 690")
    cart.add_item(db, user_id, pid, 2)
    other = auth.register(db, f"other{uuid.uuid4().hex[:8]}", "secret123").id

    mine, _ = _run(db, user_id, [tool_call("get_cart", {}), final(_answer(type_="info"))])
    theirs, _ = _run(db, other, [tool_call("get_cart", {}), final(_answer(type_="info"))])

    assert mine.tool_executions[0][1].result["cart"]["item_count"] == 2
    assert theirs.tool_executions[0][1].result["cart"]["items"] == []
    assert mine.tool_executions[0][1].product_ids == [pid]  # cart items can become cards


# --- Level 3: confirmation, nothing is executed ------------------------------------------------


def test_remove_does_not_remove_and_stops_the_turn(db, user_id):
    pid = _id(db, "Vector Air 690")
    cart.add_item(db, user_id, pid, 2)
    # Only ONE scripted step: if the loop called the model again, FakeLLM would fail
    turn, llm = _run(db, user_id, [tool_call("remove_from_cart", {"product_id": pid})])

    assert _quantities(db, user_id) == {pid: 2}  # untouched
    assert turn.stop_reason == "confirmation_required"
    assert len(llm.requests) == 1
    pending = turn.response.pending_confirmation
    assert (pending.action, pending.product_id) == ("remove_item", pid)
    assert "Vector Air 690 × 2" in pending.summary and "USD" in pending.summary
    assert turn.response.message == pending.summary  # built by the backend, not the model
    assert turn.response.product_ids == [pid]


def test_clear_does_not_clear(db, user_id):
    a, b = _id(db, "Vector Air 690"), _id(db, "Orbit Sound 458")
    cart.add_item(db, user_id, a, 1)
    cart.add_item(db, user_id, b, 2)
    turn, _ = _run(db, user_id, [tool_call("clear_cart", {})])

    assert _quantities(db, user_id) == {a: 1, b: 2}
    assert turn.response.pending_confirmation.action == "clear_cart"
    assert "2 productos (3 unidades)" in turn.response.pending_confirmation.summary


def test_clear_an_empty_cart_needs_no_confirmation(db, user_id):
    turn, _ = _run(db, user_id, [tool_call("clear_cart", {}), final(_answer(type_="info"))])
    assert turn.stop_reason == "goal_reached"
    assert turn.response.pending_confirmation is None
    assert turn.tool_executions[0][1].result["already_empty"] is True


def test_remove_something_not_in_the_cart(db, user_id):
    pid = _id(db, "Vector Air 690")
    turn, _ = _run(
        db, user_id, [tool_call("remove_from_cart", {"product_id": pid}), final(_answer())]
    )
    assert turn.tool_executions[0][1].result["error"]["code"] == "NOT_IN_CART"
    assert turn.response.pending_confirmation is None


def test_calls_after_a_confirmation_are_not_run(db, user_id):
    a, b = _id(db, "Vector Air 690"), _id(db, "Orbit Sound 458")
    cart.add_item(db, user_id, a, 1)
    step = LLMResult(
        response_id="r1",
        tool_calls=[
            ToolCall("c1", "clear_cart", "{}"),
            ToolCall("c2", "add_to_cart", json.dumps({"product_id": b, "quantity": 1})),
        ],
        usage=Usage(10, 10),
    )
    turn, _ = _run(db, user_id, [step], seen=[b])
    assert [e.call.name for _, e in turn.tool_executions] == ["clear_cart"]
    assert _quantities(db, user_id) == {a: 1}


def test_cart_change_is_reported_even_if_the_turn_falls_back(db, user_id):
    pid = _id(db, "Vector Air 690")
    turn, _ = _run(
        db,
        user_id,
        [
            tool_call("add_to_cart", {"product_id": pid, "quantity": 1}),
            final("not json"),
            final("still not json"),
        ],
        seen=[pid],
    )
    assert turn.stop_reason == "format"
    assert turn.response.ui_actions == ["refresh_cart"]  # the cart DID change: UI must refresh
    assert "ya hice cambios en tu carrito" in turn.response.message  # not hidden


def test_fallback_without_cart_change_has_no_note(db, user_id):
    turn, _ = _run(db, user_id, [final("not json"), final("still not json")])
    assert turn.stop_reason == "format"
    assert "carrito" not in turn.response.message


# --- Through the API ------------------------------------------------------------------------------


def test_chat_adds_to_the_cart_end_to_end(api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    app.dependency_overrides[get_llm] = lambda: FakeLLM(
        [
            tool_call("get_product", {"name": "Vector Air 690", "product_id": None}),
            tool_call("add_to_cart", {"product_id": pid, "quantity": 1}, call_id="c2"),
            final(_answer(message="Agregué Vector Air 690", product_ids=[pid])),
        ]
    )
    app.dependency_overrides[get_query_embedder] = lambda: EMBEDDER
    api.login()

    body = api.post("/api/chat", json={"message": "agregá los Vector Air 690"}).json()
    assert body["response"]["ui_actions"] == ["refresh_cart"]
    assert body["response"]["pending_confirmation"] is None
    items = api.get("/api/cart").json()["items"]
    assert [(i["product_id"], i["quantity"]) for i in items] == [(pid, 1)]


def test_chat_confirmation_card_through_the_api(api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    api.login()
    api.post("/api/cart/items", json={"product_id": pid, "quantity": 2})
    app.dependency_overrides[get_llm] = lambda: FakeLLM([tool_call("clear_cart", {})])
    app.dependency_overrides[get_query_embedder] = lambda: EMBEDDER

    body = api.post("/api/chat", json={"message": "vaciá el carrito"}).json()
    assert body["response"]["pending_confirmation"]["action"] == "clear_cart"
    assert body["meta"]["stop_reason"] == "confirmation_required"
    assert api.get("/api/cart").json()["item_count"] == 2  # still there
    # The card's button calls the REST endpoint directly (no LLM)
    assert api.delete("/api/cart").json()["item_count"] == 0
