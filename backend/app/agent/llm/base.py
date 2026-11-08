"""LLMProvider: the only interface the agent knows. Adapters (OpenAI, Fake) live next to it,
so the agent code never imports `openai` (AGENTS.md rule 12)."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # strict JSON schema (see schema.strict_json_schema)


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # raw JSON string, exactly as the model produced it


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True)
class LLMResult:
    response_id: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Text of every assistant message item, in order. The structured output is parsed from
    # these items (not from a concatenated output_text): the model may add an extra message.
    message_texts: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class ToolOutput:
    call_id: str
    output: str  # JSON string sent back to the model


class LLMError(Exception):
    """The LLM call failed after the SDK retries. `retryable`: worth retrying later."""

    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class LLMProvider(Protocol):
    model: str

    async def generate(
        self,
        *,
        instructions: str,
        input_messages: list[dict[str, str]] | None,
        tool_outputs: list[ToolOutput] | None,
        previous_response_id: str | None,
        tools: list[ToolSpec],
        response_schema: dict[str, Any],
    ) -> LLMResult:
        """First step of a turn: `input_messages` (history + user message).
        Next steps: `tool_outputs` + `previous_response_id` (continues the same response chain)."""
        ...
