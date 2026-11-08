"""GET /api/conversations and /api/conversations/{id}/messages. Conversations are created
through the real POST /api/chat with a scripted FakeLLM (no OpenAI)."""

import json
import uuid

import pytest

from app.agent.llm.fake import FakeLLM, final, tool_call
from app.api.chat import get_llm, get_query_embedder
from app.main import app
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration


def _answer(product_ids=(), type_="info", message="Listo") -> dict:
    return {
        "type": type_,
        "message": message,
        "product_ids": list(product_ids),
        "clarifying_question": None,
        "suggested_replies": ["Gracias"],
    }


def _recommend(request):
    products = json.loads(request["tool_outputs"][0].output)["products"]
    return final(_answer([p["product_id"] for p in products], "recommendation", "Estos van"))


def _chat(api, steps, message, conversation_id=None):
    app.dependency_overrides[get_llm] = lambda: FakeLLM(steps)
    app.dependency_overrides[get_query_embedder] = lambda: FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)
    body = {"message": message}
    if conversation_id:
        body["conversation_id"] = conversation_id
    response = api.post("/api/chat", json=body)
    assert response.status_code == 200, response.text
    return response.json()["conversation_id"]


SEARCH = {
    "query": "headphones",
    "category": "Headphones",
    "subcategory": None,
    "brand": None,
    "min_price": None,
    "max_price": None,
    "use_cases": [],
    "exclude_use_cases": [],
    "in_stock_only": True,
    "limit": 2,
}


def test_list_my_conversations_most_recent_first(api):
    api.login()
    first = _chat(api, [final(_answer())], "hola, primera conversación")
    second = _chat(api, [final(_answer())], "segunda conversación")
    _chat(api, [final(_answer(message="De nada"))], "gracias", conversation_id=first)

    body = api.get("/api/conversations").json()
    assert body["total"] == 2
    ids = [c["conversation_id"] for c in body["items"]]
    assert ids == [first, second]  # the first one had the latest activity
    latest = body["items"][0]
    assert latest["title"] == "hola, primera conversación"
    assert latest["message_count"] == 4  # 2 turns x (user + assistant)
    assert latest["last_message_preview"] == "De nada"


def test_pagination(api):
    api.login()
    for i in range(3):
        _chat(api, [final(_answer())], f"conversación {i}")
    page = api.get("/api/conversations", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert api.get("/api/conversations", params={"limit": 0}).status_code == 422
    assert api.get("/api/conversations", params={"limit": 51}).status_code == 422


def test_reopen_a_conversation_with_cards_and_tools(api):
    api.login()
    conversation = _chat(
        api, [tool_call("search_products", SEARCH), _recommend], "busco auriculares"
    )
    body = api.get(f"/api/conversations/{conversation}/messages").json()

    assert body["title"] == "busco auriculares"
    user, assistant = body["messages"]
    assert (user["role"], user["content"], user["response"], user["tools"]) == (
        "user",
        "busco auriculares",
        None,
        [],
    )
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "Estos van"
    assert assistant["response"]["type"] == "recommendation"
    assert len(assistant["response"]["product_ids"]) == 2  # the UI fetches the cards
    assert assistant["response"]["suggested_replies"] == ["Gracias"]
    [tool] = assistant["tools"]
    assert tool["tool_name"] == "search_products" and tool["step"] == 1
    assert tool["arguments"]["category"] == "Headphones"
    assert tool["is_error"] is False and tool["error_code"] is None


def test_tool_errors_are_visible(api):
    api.login()
    bad = dict(SEARCH, category="Auriculares")
    conversation = _chat(
        api, [tool_call("search_products", bad), final(_answer(type_="error"))], "auriculares"
    )
    tool = api.get(f"/api/conversations/{conversation}/messages").json()["messages"][1]["tools"][0]
    assert tool["is_error"] is True
    assert tool["error_code"] == "INVALID_ARGUMENTS"


def test_conversations_are_private(api):
    api.login()
    mine = _chat(api, [final(_answer())], "mi conversación")
    api.login()  # another user
    assert api.get("/api/conversations").json()["total"] == 0
    response = api.get(f"/api/conversations/{mine}/messages")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_unknown_or_invalid_id(api):
    api.login()
    assert api.get(f"/api/conversations/{uuid.uuid4()}/messages").status_code == 404
    assert api.get("/api/conversations/not-a-uuid/messages").status_code == 422


@pytest.mark.parametrize(
    "path", ["/api/conversations", f"/api/conversations/{uuid.uuid4()}/messages"]
)
def test_requires_login(api, path):
    assert api.get(path).status_code == 401
