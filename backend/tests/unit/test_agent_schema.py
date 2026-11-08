import json

from app.agent.guardrails import parse_response
from app.agent.llm.schema import strict_json_schema
from app.agent.response_schema import AgentResponse, ModelResponse, fallback
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
    for model in (SearchProductsArgs, ModelResponse):
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


def test_backend_only_fields_are_not_in_the_model_schema():
    """The model cannot invent a confirmation card or a cart refresh."""
    model_fields = set(strict_json_schema(ModelResponse)["properties"])
    assert "pending_confirmation" not in model_fields
    assert "ui_actions" not in model_fields
    assert {"pending_confirmation", "ui_actions"} <= set(AgentResponse.model_fields)


def test_model_cannot_smuggle_backend_fields():
    text = json.dumps({**json.loads(_answer()), "ui_actions": ["refresh_cart"]})
    response, error = parse_response([text])
    assert response is None and "ui_actions" in error  # extra="forbid"


def _refs_with_siblings(node, path="$"):
    if isinstance(node, dict):
        if "$ref" in node and len(node) > 1:
            yield path
        for key, value in node.items():
            yield from _refs_with_siblings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from _refs_with_siblings(item, f"{path}[{i}]")


def test_no_tool_schema_has_ref_with_sibling_keywords():
    """OpenAI strict mode: '$ref cannot have keywords {description}' (found with the real API:
    FakeLLM does not validate schemas). Checked for EVERY tool, present and future."""
    from app.agent.tools import TOOLS

    for tool in TOOLS.values():
        schema = strict_json_schema(tool.args_model)
        assert list(_refs_with_siblings(schema)) == [], tool.name
        for obj in _objects(schema):
            assert obj["required"] == list(obj["properties"]), tool.name
    assert list(_refs_with_siblings(strict_json_schema(ModelResponse))) == []
