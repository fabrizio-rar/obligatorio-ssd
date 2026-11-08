"""Strict JSON schema from a Pydantic model, as OpenAI's strict mode requires:
every object has all its properties in `required` and `additionalProperties: false`
(optional fields are expressed as nullable). Pydantic keeps validating on our side."""

from typing import Any

from pydantic import BaseModel

# Keywords that only add noise for the model (or are not accepted in strict mode)
_DROP = {"title", "default"}


def _strict(node: Any) -> Any:
    if isinstance(node, dict):
        out = {key: _strict(value) for key, value in node.items() if key not in _DROP}
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_strict(item) for item in node]
    return node


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    return _strict(model.model_json_schema())
