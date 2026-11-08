"""One chat turn as a workflow (docs/PLAN.md §10.2):
load conversation -> run the agent -> validate -> persist. Used by the API and the CLI."""

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMProvider
from app.agent.loop import TurnLimits, TurnResult, run_turn
from app.agent.response_schema import AgentResponse
from app.agent.state import AgentState
from app.agent.tools import ToolContext
from app.config import Settings
from app.domain.errors import DomainError
from app.models import AgentStateRow, ChatMessage, Conversation, ToolCallLog
from app.retrieval.embeddings import Embedder

TITLE_LENGTH = 60


class TurnMeta(BaseModel):
    steps: int
    stop_reason: str
    tools_used: list[str]
    input_tokens: int
    output_tokens: int
    latency_ms: int
    model: str


class ChatTurn(BaseModel):
    conversation_id: uuid.UUID
    response: AgentResponse
    meta: TurnMeta


def load_history(session: Session, conversation_id: uuid.UUID, limit: int) -> list[dict[str, str]]:
    """Last `limit` messages, oldest first, as {role, content} for the model."""
    if limit == 0:
        return []
    rows = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
    ).all()
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def _save_turn(
    session: Session,
    conversation: Conversation,
    user_text: str,
    turn: TurnResult,
    state: AgentState,
    meta: TurnMeta,
) -> None:
    session.add(ChatMessage(conversation_id=conversation.id, role="user", content=user_text))
    assistant = ChatMessage(
        conversation_id=conversation.id,
        role="assistant",
        content=turn.response.message,
        structured={
            "response": turn.response.model_dump(mode="json"),
            "meta": meta.model_dump(mode="json"),
            "dropped_product_ids": turn.dropped_product_ids,
        },
    )
    session.add(assistant)
    session.flush()  # assistant.id for the tool logs
    for step, execution in turn.tool_executions:
        session.add(
            ToolCallLog(
                message_id=assistant.id,
                step=step,
                tool_name=execution.call.name,
                arguments=execution.arguments,
                result=execution.result,
                is_error=execution.is_error,
                latency_ms=execution.latency_ms,
            )
        )
    session.merge(AgentStateRow(conversation_id=conversation.id, state=state.model_dump()))


async def chat_turn(
    session: Session,
    llm: LLMProvider,
    embedder: Embedder | None,
    settings: Settings,
    message: str,
    conversation_id: uuid.UUID | None = None,
    *,
    user_id: int,
) -> ChatTurn:
    """Raises DomainError (CONVERSATION_NOT_FOUND) and LLMError (the model failed).
    On any error nothing is saved: the turn is all or nothing.
    `user_id` comes from the session token, never from the model."""
    if conversation_id is None:
        conversation = Conversation(id=uuid.uuid4(), user_id=user_id, title=message[:TITLE_LENGTH])
        session.add(conversation)
        history: list[dict[str, str]] = []
        state = AgentState()
    else:
        conversation = session.get(Conversation, conversation_id)
        # Someone else's conversation looks exactly like a missing one (no info leak)
        if conversation is None or conversation.user_id != user_id:
            raise DomainError(
                "CONVERSATION_NOT_FOUND", "Conversation not found", {"id": str(conversation_id)}
            )
        history = load_history(session, conversation.id, settings.agent_history_messages)
        row = session.get(AgentStateRow, conversation.id)
        state = AgentState.model_validate(row.state) if row else AgentState()

    limits = TurnLimits(
        max_steps=settings.agent_max_steps,
        timeout_seconds=settings.agent_turn_timeout_seconds,
        max_tokens=settings.agent_max_tokens_per_turn,
    )
    try:
        turn = await run_turn(
            llm, ToolContext(session, embedder, user_id=user_id), limits, history, message, state
        )
        meta = TurnMeta(
            steps=turn.steps,
            stop_reason=turn.stop_reason,
            tools_used=[e.call.name for _, e in turn.tool_executions],
            input_tokens=turn.usage.input_tokens,
            output_tokens=turn.usage.output_tokens,
            latency_ms=turn.latency_ms,
            model=llm.model,
        )
        _save_turn(session, conversation, message, turn, state, meta)
        session.commit()
    except Exception:
        session.rollback()
        raise
    return ChatTurn(conversation_id=conversation.id, response=turn.response, meta=meta)
