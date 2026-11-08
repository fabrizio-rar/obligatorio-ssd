"""Agent loop: one user turn (docs/PLAN.md §10.8, without streaming).

Stop conditions (§10.7.3), whichever comes first:
    goal_reached   the model returns a valid final answer
    max_steps      AGENT_MAX_STEPS model calls
    budget         AGENT_TURN_TIMEOUT_SECONDS or AGENT_MAX_TOKENS_PER_TURN
    loop           the same tool with the same arguments twice in the turn
    format         the answer does not match the schema, even after 1 format retry
    confirmation   a level-3 tool (remove/clear) needs the user's click: the turn ends with
                   a card built by the backend; the model gets no further step
    error          irrecoverable LLM error -> LLMError propagates to the caller

Retries of transient LLM errors (429 / 5xx / timeout) are done by the SDK. Tool and
business errors are NOT retried: they go back to the model as data.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.agent.guardrails import check_product_ids, parse_response
from app.agent.llm.base import LLMProvider, ToolOutput, Usage
from app.agent.llm.schema import strict_json_schema
from app.agent.response_schema import AgentResponse, ModelResponse, PendingAction, fallback
from app.agent.state import AgentState, summary
from app.agent.tools import ToolContext, ToolExecution, execute_tool, tool_specs

SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
RESPONSE_SCHEMA = strict_json_schema(ModelResponse)  # what the MODEL may write
FORMAT_RETRY_MESSAGE = (
    "Your last answer did not match the required JSON schema ({error}). "
    "Reply again with only the JSON object."
)


@dataclass(frozen=True)
class TurnLimits:
    max_steps: int
    timeout_seconds: float
    max_tokens: int


@dataclass
class TurnResult:
    response: AgentResponse
    stop_reason: str
    steps: int
    tool_executions: list[tuple[int, ToolExecution]] = field(default_factory=list)  # (step, ...)
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    dropped_product_ids: list[str] = field(default_factory=list)


def build_instructions(state: AgentState, ctx: ToolContext) -> str:
    context = summary(state, ctx.session)
    return f"{SYSTEM_PROMPT}\n\n# Conversation context\n{context}" if context else SYSTEM_PROMPT


def _confirmation_response(pending: PendingAction) -> AgentResponse:
    """Built by the backend with DB data: amounts cannot be wrong, and the model never gets
    the chance to say "done, I removed it"."""
    return AgentResponse(
        type="cart_update",
        message=pending.summary,
        product_ids=[pending.product_id] if pending.product_id else [],
        clarifying_question=None,
        suggested_replies=[],
        pending_confirmation=pending,
    )


def _signature(execution_name: str, arguments: str) -> str:
    try:
        normalized = json.dumps(json.loads(arguments), sort_keys=True)
    except json.JSONDecodeError:
        normalized = arguments
    return f"{execution_name}:{normalized}"


async def run_turn(
    llm: LLMProvider,
    ctx: ToolContext,
    limits: TurnLimits,
    history: list[dict[str, str]],
    user_text: str,
    state: AgentState,
) -> TurnResult:
    started = time.monotonic()
    instructions = build_instructions(state, ctx)
    tools = tool_specs(ctx.session)
    result = TurnResult(response=fallback("max_steps"), stop_reason="max_steps", steps=0)
    seen = set(state.seen_product_ids)
    ctx.seen_product_ids = seen  # same set: tools see what the loop adds
    ui_actions: list[str] = []
    signatures: set[str] = set()
    format_retried = False

    # First call: history + user message. Next calls: tool outputs chained to the response.
    input_messages: list[dict[str, str]] | None = [*history, {"role": "user", "content": user_text}]
    tool_outputs: list[ToolOutput] | None = None
    previous_response_id: str | None = None

    def finish(response: ModelResponse, reason: str) -> TurnResult:
        # The backend adds what the tools did (the model cannot set these fields)
        result.response = AgentResponse(
            **response.model_dump(exclude={"ui_actions"}),
            ui_actions=list(dict.fromkeys(ui_actions)),
        )
        result.stop_reason = reason
        result.latency_ms = int((time.monotonic() - started) * 1000)
        state.remember(list(seen))
        state.last_turn.steps = result.steps
        state.last_turn.tools_used = [e.call.name for _, e in result.tool_executions]
        state.last_turn.stop_reason = reason
        if reason == "goal_reached":
            state.last_shown = response.product_ids
        return result

    for step in range(1, limits.max_steps + 1):
        remaining = limits.timeout_seconds - (time.monotonic() - started)
        if remaining <= 0 or result.usage.total >= limits.max_tokens:
            return finish(fallback("budget", "refresh_cart" in ui_actions), "budget")

        try:
            llm_result = await asyncio.wait_for(
                llm.generate(
                    instructions=instructions,
                    input_messages=input_messages,
                    tool_outputs=tool_outputs,
                    previous_response_id=previous_response_id,
                    tools=tools,
                    response_schema=RESPONSE_SCHEMA,
                ),
                timeout=remaining,
            )
        except TimeoutError:
            return finish(fallback("budget", "refresh_cart" in ui_actions), "budget")

        result.steps = step
        result.usage = Usage(
            result.usage.input_tokens + llm_result.usage.input_tokens,
            result.usage.output_tokens + llm_result.usage.output_tokens,
        )
        previous_response_id = llm_result.response_id

        # The model wants to use tools: run them and send the results back
        if llm_result.tool_calls:
            outputs = []
            for call in llm_result.tool_calls:
                signature = _signature(call.name, call.arguments)
                if signature in signatures:
                    return finish(fallback("loop", "refresh_cart" in ui_actions), "loop")
                signatures.add(signature)
                execution = execute_tool(ctx, call)
                result.tool_executions.append((step, execution))
                seen.update(execution.product_ids)
                ui_actions.extend(execution.ui_actions)
                if execution.pending_confirmation is not None:
                    # Stop: human confirmation needed. Later calls of this step are not run.
                    pending = execution.pending_confirmation
                    return finish(_confirmation_response(pending), "confirmation_required")
                outputs.append(ToolOutput(call.call_id, json.dumps(execution.result, default=str)))
            input_messages, tool_outputs = None, outputs
            continue

        # Final answer: validate it
        response, error = parse_response(llm_result.message_texts)
        if response is None:
            if format_retried:
                return finish(fallback("format", "refresh_cart" in ui_actions), "format")
            format_retried = True
            message = FORMAT_RETRY_MESSAGE.format(error=error[:500])
            input_messages, tool_outputs = [{"role": "user", "content": message}], None
            continue

        response, dropped = check_product_ids(response, seen, ctx.session)
        result.dropped_product_ids = dropped
        return finish(response, "goal_reached")

    return finish(fallback("max_steps", "refresh_cart" in ui_actions), "max_steps")
