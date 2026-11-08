import json

from app.agent.guardrails import parse_response
from app.agent.llm.schema import strict_json_schema
from app.agent.response_schema import AgentResponse, fallback
from app.agent.tools import SearchProductsArgs


def _objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _objects(item)


def test_strict_schemas_require_every_property_and_forbid_extras():
    for model in (SearchProductsArgs, AgentResponse):
        schema = strict_json_schema(model)
        objects = list(_objects(schema))
        assert objects
        for obj in objects:
            assert obj["required"] == list(obj["properties"])
            assert obj["additionalProperties"] is False
        text = json.dumps(schema)
        assert '"default"' not in text and '"title"' not in text


def test_search_args_expose_the_closed_vocabulary_as_enums():
    text = json.dumps(strict_json_schema(SearchProductsArgs))
    assert '"Headphones"' in text and '"video calls"' in text and '"air travel"' in text


def _answer(**overrides) -> str:
    data = {
        "type": "recommendation",
        "message": "Te recomiendo estos",
        "product_ids": ["MN-HDP-0001"],
        "clarifying_question": None,
        "suggested_replies": [],
    }
    data.update(overrides)
    return json.dumps(data)


def test_parse_takes_the_last_valid_message_item():
    response, error = parse_response([_answer(message="primero"), "texto suelto", _answer()])
    assert error is None
    assert response.message == "Te recomiendo estos"


def test_parse_skips_an_extra_invalid_message_after_the_answer():
    response, _ = parse_response([_answer(), "Here is your answer!"])
    assert response is not None


def test_parse_reports_invalid_output():
    response, error = parse_response([_answer(type="purchase")])
    assert response is None and "type" in error
    response, error = parse_response([])
    assert response is None and error


def test_fallback_never_claims_an_action():
    for reason in ("format", "max_steps", "budget", "loop"):
        response = fallback(reason)
        assert response.type == "error"
        assert response.product_ids == []
        assert "compr" not in response.message.lower()
