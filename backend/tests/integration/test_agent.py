"""Agent loop + tools + persistence with FakeLLM (scripted) against the real catalog."""

import asyncio
import json
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent import tools as tools_module
from app.agent.llm.base import LLMError, LLMResult, ToolCall, Usage
from app.agent.llm.fake import FakeLLM, final, tool_call
from app.agent.loop import FORMAT_RETRY_MESSAGE, TurnLimits, run_turn
from app.agent.service import chat_turn
from app.agent.state import AgentState
from app.agent.tools import ToolContext
from app.api.chat import get_llm, get_query_embedder
from app.auth import service as auth
from app.config import Settings
from app.db import get_db
from app.domain.errors import DomainError
from app.main import app
from app.models import ChatMessage, Conversation, Product, ToolCallLog, User
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration

EMBEDDER = FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)
LIMITS = TurnLimits(max_steps=6, timeout_seconds=30, max_tokens=100_000)
SEARCH = {
    "query": "headphones for calls",
    "category": "Headphones",
    "subcategory": None,
    "brand": None,
    "min_price": None,
    "max_price": 200,
    "use_cases": ["calls"],
    "exclude_use_cases": [],
    "in_stock_only": True,
    "limit": 3,
}


def _answer(product_ids=(), type_="recommendation", message="Te recomiendo estos") -> dict:
    return {
        "type": type_,
        "message": message,
        "product_ids": list(product_ids),
        "clarifying_question": None,
        "suggested_replies": [],
    }


def _recommend_from_search(request) -> LLMResult:
    """Final step that recommends whatever the search returned (like a real model would)."""
    products = json.loads(request["tool_outputs"][0].output)["products"]
    return final(_answer([p["product_id"] for p in products]))


def _owner(db: Session) -> int:
    """The user that owns the conversations of these tests (the token gives it in the API)."""
    user = db.scalar(select(User).where(User.username == "agent_tester"))
    return (user or auth.register(db, "agent_tester", "secret123")).id


def _run(db, llm, state=None, history=(), text="busco auriculares", limits=LIMITS):
    ctx = ToolContext(db, EMBEDDER, user_id=_owner(db))
    return asyncio.run(run_turn(llm, ctx, limits, list(history), text, state or AgentState()))


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    return catalog_db


# --- Loop ---------------------------------------------------------------------------------------


def test_search_then_recommend(db):
    llm = FakeLLM([tool_call("search_products", SEARCH), _recommend_from_search])
    state = AgentState()
    turn = _run(db, llm, state)

    assert turn.stop_reason == "goal_reached"
    assert turn.steps == 2
    assert turn.response.type == "recommendation"
    assert len(turn.response.product_ids) == 3
    assert state.last_shown == turn.response.product_ids
    assert set(turn.response.product_ids) <= set(state.seen_product_ids)

    first, second = llm.requests
    assert first["input_messages"][-1] == {"role": "user", "content": "busco auriculares"}
    assert [t.name for t in first["tools"]] == [
        "search_products",
        "get_product",
        "get_cart",
        "add_to_cart",
        "update_cart_item",
        "remove_from_cart",
        "clear_cart",
    ]
    assert "calls -> " in first["tools"][0].description  # use cases per category
    # Second step: only the tool output, chained to the previous response
    assert second["input_messages"] is None
    assert second["previous_response_id"] == "resp_call_1"
    result = json.loads(second["tool_outputs"][0].output)
    assert result["ok"] is True
    product = result["products"][0]
    assert product["price"].startswith("USD ")  # price from the DB
    assert {"stock", "recommended_for", "key_features"} <= set(product)


def test_invalid_arguments_never_reach_the_search(db, monkeypatch):
    def must_not_run(*_args, **_kwargs):
        raise AssertionError("search() called with invalid arguments")

    monkeypatch.setattr(tools_module, "search", must_not_run)
    bad = dict(SEARCH, category="Auriculares")  # not in the enum
    llm = FakeLLM([tool_call("search_products", bad), final(_answer(type_="error"))])
    turn = _run(db, llm)

    execution = turn.tool_executions[0][1]
    assert execution.is_error
    assert execution.result["error"]["code"] == "INVALID_ARGUMENTS"
    assert json.loads(llm.requests[1]["tool_outputs"][0].output)["ok"] is False
    assert turn.stop_reason == "goal_reached"  # the model got the error and answered


def test_business_rule_error_goes_back_to_the_model(db):
    bad = dict(SEARCH, subcategory="Gaming")  # not a Headphones subcategory
    llm = FakeLLM([tool_call("search_products", bad), final(_answer(type_="clarification"))])
    turn = _run(db, llm)
    assert turn.tool_executions[0][1].result["error"]["code"] == "INVALID_ARGUMENTS"


def test_unknown_tool_and_broken_json_are_reported(db):
    calls = LLMResult(
        response_id="r1",
        tool_calls=[ToolCall("c1", "buy_now", "{}"), ToolCall("c2", "search_products", "{nope")],
        usage=Usage(10, 10),
    )
    llm = FakeLLM([calls, final(_answer(type_="info"))])
    turn = _run(db, llm)
    codes = [e.result["error"]["code"] for _, e in turn.tool_executions]
    assert codes == ["UNKNOWN_TOOL", "INVALID_ARGUMENTS"]


def test_made_up_and_inactive_ids_are_dropped(db):
    inactive = db.scalar(select(Product.id).where(Product.active.is_(False)))
    state = AgentState(seen_product_ids=[inactive])  # even if it was "seen"

    def answer_with_fakes(request):
        real = json.loads(request["tool_outputs"][0].output)["products"][0]["product_id"]
        return final(_answer([real, "MN-FAKE-9999", inactive, real]))

    llm = FakeLLM([tool_call("search_products", SEARCH), answer_with_fakes])
    turn = _run(db, llm, state)

    assert len(turn.response.product_ids) == 1
    assert set(turn.dropped_product_ids) == {"MN-FAKE-9999", inactive}


def test_answer_without_search_cannot_show_products(db):
    some_id = db.scalar(select(Product.id).where(Product.active.is_(True)))
    turn = _run(db, FakeLLM([final(_answer([some_id]))]))
    assert turn.response.product_ids == []
    assert turn.dropped_product_ids == [some_id]


def test_format_retry_once_then_ok(db):
    llm = FakeLLM([final("Claro, acá tenés"), final(_answer(type_="info"))])
    turn = _run(db, llm)

    assert turn.stop_reason == "goal_reached"
    assert turn.steps == 2
    retry = llm.requests[1]["input_messages"][0]["content"]
    assert retry.startswith(FORMAT_RETRY_MESSAGE.split("(")[0])


def test_format_fails_twice_gives_controlled_fallback(db):
    turn = _run(db, FakeLLM([final("no json"), final("still no json")]))
    assert turn.stop_reason == "format"
    assert turn.response.type == "error"
    assert "reformular" in turn.response.message


def test_stop_on_max_steps(db):
    steps = [
        tool_call("search_products", dict(SEARCH, query=f"headphones {i}"), call_id=f"c{i}")
        for i in range(3)
    ]
    turn = _run(db, FakeLLM(steps), limits=TurnLimits(3, 30, 100_000))
    assert turn.stop_reason == "max_steps"
    assert turn.steps == 3
    assert turn.response.type == "error"


def test_stop_on_loop(db):
    same = tool_call("search_products", SEARCH)
    turn = _run(db, FakeLLM([same, same]))
    assert turn.stop_reason == "loop"
    assert len(turn.tool_executions) == 1  # the repeated call is not executed


def test_stop_on_token_budget(db):
    turn = _run(
        db,
        FakeLLM([tool_call("search_products", SEARCH), final(_answer())]),
        limits=TurnLimits(6, 30, max_tokens=50),  # first step already uses 120
    )
    assert turn.stop_reason == "budget"
    assert turn.steps == 1


def test_stop_on_time_budget(db):
    def slow(_request):
        time.sleep(0.2)
        return tool_call("search_products", SEARCH)

    turn = _run(db, FakeLLM([slow, final(_answer())]), limits=TurnLimits(6, 0.1, 100_000))
    assert turn.stop_reason == "budget"


def test_llm_error_propagates(db):
    llm = FakeLLM([LLMError("UNAVAILABLE", "down", retryable=True)])
    with pytest.raises(LLMError):
        _run(db, llm)


def test_previous_products_are_summarized_in_the_instructions(db):
    ids = db.scalars(select(Product.id).where(Product.active.is_(True)).limit(2)).all()
    llm = FakeLLM([final(_answer(type_="info"))])
    _run(db, llm, AgentState(last_shown=list(ids), seen_product_ids=list(ids)))
    instructions = llm.requests[0]["instructions"]
    assert "1) " in instructions and ids[0] in instructions and ids[1] in instructions


# --- get_product ------------------------------------------------------------------------------


def _get(name=None, product_id=None):
    return {"name": name, "product_id": product_id}


def test_get_product_by_name_returns_full_sheet(db):
    llm = FakeLLM(
        [tool_call("get_product", _get(name="Vector Air 690")), final(_answer(type_="info"))]
    )
    turn = _run(db, llm, text="¿Lo puedo retirar en Colonia?")

    execution = turn.tool_executions[0][1]
    product = execution.result["product"]
    assert product["status"] == "available"
    assert product["price"].startswith("USD ")
    colonia = next(w for w in product["stock_by_warehouse"] if w["warehouse_id"] == "WH-COL-001")
    assert colonia["available"] == 0
    assert "Active Noise Cancellation: No" in product["specs"]
    assert execution.product_ids == [product["product_id"]]


def test_discontinued_then_alternatives(db):
    cedar = db.scalar(select(Product.id).where(Product.name == "Cedar Air 243"))

    def answer(request):
        alternatives = json.loads(request["tool_outputs"][0].output)["products"]
        return final(
            _answer(
                [cedar, *[p["product_id"] for p in alternatives]],
                message="Está discontinuado; te muestro alternativas",
            )
        )

    llm = FakeLLM(
        [
            tool_call("get_product", _get(name="Cedar Air 243")),
            tool_call("search_products", dict(SEARCH, query="headphones"), call_id="c2"),
            answer,
        ]
    )
    turn = _run(db, llm, text="Quiero los Cedar Air 243")

    first = turn.tool_executions[0][1]
    assert first.result["product"]["status"] == "discontinued"
    assert "price" not in first.result["product"]
    assert first.product_ids == []  # never becomes a card
    assert cedar not in turn.response.product_ids
    assert cedar in turn.dropped_product_ids
    assert len(turn.response.product_ids) == 3  # the alternatives


def test_get_product_duplicate_names_are_listed(db):
    llm = FakeLLM(
        [
            tool_call("get_product", _get(name="Kairo Drive Pro 2TB")),
            final(_answer(type_="clarification")),
        ]
    )
    execution = _run(db, llm).tool_executions[0][1]
    assert execution.result["ambiguous"] is True
    assert len(execution.result["matches"]) == 2
    assert len(execution.product_ids) == 2


@pytest.mark.parametrize(
    ("arguments", "code"),
    [
        (_get(), "INVALID_ARGUMENTS"),  # neither
        (_get(name="Vector Air 690", product_id="MN-HDP-0004"), "INVALID_ARGUMENTS"),  # both
        (_get(product_id="MN-XXX-0000"), "NOT_FOUND"),
        (_get(name="Producto Inexistente 9000"), "NOT_FOUND"),
    ],
)
def test_get_product_errors(db, arguments, code):
    llm = FakeLLM([tool_call("get_product", arguments), final(_answer(type_="info"))])
    execution = _run(db, llm).tool_executions[0][1]
    assert execution.is_error
    assert execution.result["error"]["code"] == code


def test_both_tools_are_offered(db):
    llm = FakeLLM([final(_answer(type_="info"))])
    _run(db, llm)
    assert [t.name for t in llm.requests[0]["tools"]] == [
        "search_products",
        "get_product",
        "get_cart",
        "add_to_cart",
        "update_cart_item",
        "remove_from_cart",
        "clear_cart",
    ]


# --- Service: conversation persistence ----------------------------------------------------------


def _chat_turn(db, *args, **kwargs):
    return chat_turn(db, *args, user_id=_owner(db), **kwargs)


def _settings(**overrides) -> Settings:
    return Settings(database_url="postgresql+psycopg://unused", **overrides)


def test_turns_are_persisted_with_history_and_tool_logs(db):
    llm = FakeLLM([tool_call("search_products", SEARCH), _recommend_from_search])
    first = asyncio.run(_chat_turn(db, llm, EMBEDDER, _settings(), "busco auriculares"))

    messages = db.scalars(
        select(ChatMessage).where(ChatMessage.conversation_id == first.conversation_id)
    ).all()
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[1].structured["response"]["product_ids"] == first.response.product_ids
    logs = db.scalars(select(ToolCallLog).where(ToolCallLog.message_id == messages[1].id)).all()
    assert [(log.step, log.tool_name, log.is_error) for log in logs] == [
        (1, "search_products", False)
    ]
    assert first.meta.tools_used == ["search_products"]

    # Second turn: history goes to the model, state remembers what was shown
    llm2 = FakeLLM([final(_answer(first.response.product_ids[:1], message="El primero"))])
    second = asyncio.run(
        _chat_turn(db, llm2, EMBEDDER, _settings(), "y el primero?", first.conversation_id)
    )
    sent = llm2.requests[0]["input_messages"]
    assert sent[0] == {"role": "user", "content": "busco auriculares"}
    assert sent[1]["role"] == "assistant"
    assert sent[-1] == {"role": "user", "content": "y el primero?"}
    # The id came from a tool in the PREVIOUS turn: still allowed
    assert second.response.product_ids == first.response.product_ids[:1]


def test_history_is_limited(db):
    llm = FakeLLM([final(_answer(type_="info"))] * 3)
    turn = asyncio.run(_chat_turn(db, llm, EMBEDDER, _settings(), "hola"))
    for text in ("dos", "tres"):
        asyncio.run(
            _chat_turn(
                db, llm, EMBEDDER, _settings(agent_history_messages=2), text, turn.conversation_id
            )
        )
    assert len(llm.requests[-1]["input_messages"]) == 3  # 2 history + the new message


def test_failed_turn_saves_nothing(db):
    before = db.scalar(select(func.count()).select_from(Conversation))
    llm = FakeLLM([LLMError("UNAVAILABLE", "down", retryable=True)])
    with pytest.raises(LLMError):
        asyncio.run(_chat_turn(db, llm, EMBEDDER, _settings(), "hola"))
    assert db.scalar(select(func.count()).select_from(Conversation)) == before


def test_unknown_conversation(db):
    with pytest.raises(DomainError) as info:
        asyncio.run(_chat_turn(db, FakeLLM([]), EMBEDDER, _settings(), "hola", uuid.uuid4()))
    assert info.value.code == "CONVERSATION_NOT_FOUND"


# --- API ----------------------------------------------------------------------------------------


@pytest.fixture
def client(db):
    def use(llm):
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_llm] = lambda: llm
        app.dependency_overrides[get_query_embedder] = lambda: EMBEDDER
        http = TestClient(app)
        name = f"u{uuid.uuid4().hex[:10]}"
        http.post("/api/auth/register", json={"username": name, "password": "secret123"})
        token = http.post(
            "/api/auth/login", json={"username": name, "password": "secret123"}
        ).json()["token"]
        http.headers["Authorization"] = f"Bearer {token}"
        return http

    yield use
    app.dependency_overrides.clear()


def test_chat_endpoint_multi_turn(client):
    llm = FakeLLM(
        [tool_call("search_products", SEARCH), _recommend_from_search, final(_answer(type_="info"))]
    )
    http = client(llm)
    first = http.post("/api/chat", json={"message": "auriculares para llamadas hasta 200"})
    assert first.status_code == 200
    body = first.json()
    assert body["response"]["type"] == "recommendation"
    assert len(body["response"]["product_ids"]) == 3
    assert body["meta"]["stop_reason"] == "goal_reached"
    assert body["meta"]["tools_used"] == ["search_products"]

    second = http.post(
        "/api/chat", json={"message": "gracias", "conversation_id": body["conversation_id"]}
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == body["conversation_id"]


def test_chat_disabled_without_key(client):
    response = client(None).post("/api/chat", json={"message": "hola"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAT_DISABLED"


def test_chat_validation_errors(client):
    http = client(FakeLLM([]))
    assert http.post("/api/chat", json={"message": ""}).status_code == 422
    assert http.post("/api/chat", json={"message": "   "}).status_code == 422
    assert http.post("/api/chat", json={"message": "x" * 2001}).status_code == 422
    unknown = http.post(
        "/api/chat",
        json={"message": "hola", "conversation_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_chat_llm_errors(client):
    down = client(FakeLLM([LLMError("UNAVAILABLE", "down", retryable=True)]))
    response = down.post("/api/chat", json={"message": "hola"})
    assert response.status_code == 503
    assert response.json()["error"]["details"]["retryable"] is True

    broken = client(FakeLLM([LLMError("AUTH", "bad key", retryable=False)]))
    response = broken.post("/api/chat", json={"message": "hola"})
    assert response.status_code == 502
    assert response.json()["error"]["details"]["retryable"] is False


def test_chat_requires_login(client):
    http = client(FakeLLM([]))
    del http.headers["Authorization"]
    response = http.post("/api/chat", json={"message": "hola"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_cannot_continue_someone_elses_conversation(client):
    alice = client(FakeLLM([final(_answer(type_="info"))]))
    conversation = alice.post("/api/chat", json={"message": "hola"}).json()["conversation_id"]

    bob = client(FakeLLM([]))  # new user, new token
    response = bob.post("/api/chat", json={"message": "hola", "conversation_id": conversation})
    assert response.status_code == 404  # looks like it does not exist: no info leak
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"
