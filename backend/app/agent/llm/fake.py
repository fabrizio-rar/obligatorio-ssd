"""FakeLLM: scripted responses for tests. pytest never calls OpenAI (AGENTS.md)."""

import json
from collections.abc import Callable
from typing import Any

from app.agent.llm.base import LLMResult, ToolCall, ToolOutput, ToolSpec, Usage

Step = LLMResult | Exception | Callable[[dict[str, Any]], LLMResult]


def tool_call(name: str, arguments: dict[str, Any] | str, call_id: str = "call_1") -> LLMResult:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return LLMResult(
        response_id=f"resp_{call_id}",
        tool_calls=[ToolCall(call_id, name, raw)],
        usage=Usage(100, 20),
    )


def final(payload: dict[str, Any] | str, response_id: str = "resp_final") -> LLMResult:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return LLMResult(response_id=response_id, message_texts=[text], usage=Usage(150, 60))


class FakeLLM:
    """Returns the scripted steps in order and records every request it receives."""

    model = "fake-llm"

    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.requests: list[dict[str, Any]] = []

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
        request = {
            "instructions": instructions,
            "input_messages": input_messages,
            "tool_outputs": tool_outputs,
            "previous_response_id": previous_response_id,
            "tools": tools,
        }
        self.requests.append(request)
        if not self.steps:
            raise AssertionError("FakeLLM ran out of scripted steps")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(request) if callable(step) else step
