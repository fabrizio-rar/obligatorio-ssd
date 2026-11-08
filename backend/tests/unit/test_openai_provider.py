import asyncio
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.agent.llm.base import LLMError, ToolOutput, ToolSpec
from app.agent.llm.openai_provider import OpenAIResponsesProvider

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")
TOOLS = [ToolSpec("search_products", "Search", {"type": "object", "properties": {}})]


def _response():
    return SimpleNamespace(
        id="resp_1",
        output=[
            SimpleNamespace(type="reasoning"),
            SimpleNamespace(
                type="function_call",
                call_id="c1",
                name="search_products",
                arguments='{"query": "x"}',
            ),
            SimpleNamespace(
                type="message",
                content=[SimpleNamespace(type="output_text", text='{"a": 1}')],
            ),
        ],
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
    )


class FakeResponses:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return _response()


def _provider(error=None):
    responses = FakeResponses(error)
    client = SimpleNamespace(responses=responses)
    return OpenAIResponsesProvider("k", "gpt-6-luna", client=client), responses


def _generate(provider, **kwargs):
    defaults = dict(
        instructions="sys",
        input_messages=None,
        tool_outputs=None,
        previous_response_id=None,
        tools=TOOLS,
        response_schema={"type": "object"},
    )
    return asyncio.run(provider.generate(**{**defaults, **kwargs}))


def test_first_step_sends_messages_strict_tools_and_schema():
    provider, responses = _provider()
    result = _generate(provider, input_messages=[{"role": "user", "content": "hola"}])

    call = responses.calls[0]
    assert call["model"] == "gpt-6-luna"
    assert call["input"] == [{"role": "user", "content": "hola"}]
    assert call["tools"][0]["strict"] is True
    assert call["text"]["format"]["strict"] is True
    assert call["reasoning"] == {"effort": "low"}
    assert call["store"] is True
    assert result.response_id == "resp_1"
    assert [(t.call_id, t.name) for t in result.tool_calls] == [("c1", "search_products")]
    assert result.message_texts == ['{"a": 1}']
    assert (result.usage.input_tokens, result.usage.output_tokens) == (120, 30)


def test_next_steps_send_tool_outputs_chained_to_previous_response():
    provider, responses = _provider()
    _generate(provider, tool_outputs=[ToolOutput("c1", '{"ok": true}')], previous_response_id="r0")

    call = responses.calls[0]
    assert call["input"] == [
        {"type": "function_call_output", "call_id": "c1", "output": '{"ok": true}'}
    ]
    assert call["previous_response_id"] == "r0"
    assert call["instructions"] == "sys"  # instructions are not inherited: always sent


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            openai.AuthenticationError(
                "x", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            "AUTH",
            False,
        ),
        (
            openai.BadRequestError("x", response=httpx2.Response(400, request=REQUEST), body=None),
            "BAD_REQUEST",
            False,
        ),
        (
            openai.RateLimitError("x", response=httpx2.Response(429, request=REQUEST), body=None),
            "UNAVAILABLE",
            True,
        ),
        (openai.APIConnectionError(request=REQUEST), "UNAVAILABLE", True),
    ],
)
def test_api_errors_are_mapped(error, code, retryable):
    provider, _ = _provider(error)
    with pytest.raises(LLMError) as info:
        _generate(provider, input_messages=[{"role": "user", "content": "x"}])
    assert (info.value.code, info.value.retryable) == (code, retryable)
