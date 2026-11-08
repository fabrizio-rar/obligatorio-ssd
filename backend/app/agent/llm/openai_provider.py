"""OpenAI adapter (Responses API, async). The ONLY agent file that imports `openai`.

- Tools are declared with strict: true; the final answer uses a strict JSON schema.
- Steps inside one turn are chained with previous_response_id (requires store=True), so
  OpenAI keeps the reasoning items between a tool call and its result.
- 429 / 5xx / timeouts are retried by the SDK (max_retries, with backoff).
"""

from typing import Any

import openai

from app.agent.llm.base import LLMError, LLMResult, ToolCall, ToolOutput, ToolSpec, Usage


class OpenAIResponsesProvider:
    def __init__(
        self,
        api_key: str,
        model: str,
        reasoning_effort: str = "low",
        timeout: float = 60,
        max_retries: int = 2,
        client: Any = None,  # injectable for tests
    ) -> None:
        self.model = model
        self.reasoning_effort = reasoning_effort
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

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
        if tool_outputs:
            items: list[dict[str, Any]] = [
                {"type": "function_call_output", "call_id": t.call_id, "output": t.output}
                for t in tool_outputs
            ]
        else:
            items = [{"role": m["role"], "content": m["content"]} for m in input_messages or []]

        try:
            response = await self._client.responses.create(
                model=self.model,
                instructions=instructions,  # not inherited through previous_response_id
                input=items,
                previous_response_id=previous_response_id,
                tools=[
                    {
                        "type": "function",
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                        "strict": True,
                    }
                    for t in tools
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "agent_response",
                        "schema": response_schema,
                        "strict": True,
                    }
                },
                reasoning={"effort": self.reasoning_effort},
                store=True,
            )
        except openai.AuthenticationError as error:
            raise LLMError("AUTH", "OpenAI rejected the API key (401)", False) from error
        except openai.PermissionDeniedError as error:
            raise LLMError("FORBIDDEN", f"No access to model {self.model} (403)", False) from error
        except openai.BadRequestError as error:
            # A bug on our side (schema, parameters): log it, do not retry
            raise LLMError("BAD_REQUEST", f"OpenAI rejected the request: {error}", False) from error
        except (
            openai.RateLimitError,
            openai.APIConnectionError,  # includes timeouts
            openai.InternalServerError,
        ) as error:
            raise LLMError("UNAVAILABLE", f"OpenAI unavailable: {error}", True) from error

        return _to_result(response)


def _to_result(response: Any) -> LLMResult:
    tool_calls: list[ToolCall] = []
    texts: list[str] = []
    for item in response.output:
        if item.type == "function_call":
            tool_calls.append(ToolCall(item.call_id, item.name, item.arguments))
        elif item.type == "message":
            text = "".join(c.text for c in item.content if c.type == "output_text")
            if text:
                texts.append(text)
    usage = response.usage
    return LLMResult(
        response_id=response.id,
        tool_calls=tool_calls,
        message_texts=texts,
        usage=Usage(
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        ),
    )
