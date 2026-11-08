"""Read the user's saved conversations (for the chat history and to reopen one).
Writes happen in agent/service.py, one turn at a time."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.models import ChatMessage, Conversation, ToolCallLog

MAX_LIMIT = 50
PREVIEW_LENGTH = 120


class ConversationSummary(BaseModel):
    conversation_id: uuid.UUID
    title: str
    created_at: datetime
    last_message_at: datetime
    message_count: int
    last_message_preview: str


class ConversationList(BaseModel):
    items: list[ConversationSummary]
    total: int
    limit: int
    offset: int


class ToolCallSummary(BaseModel):
    """For the "ver tools usadas" panel. The full result stays in the DB (it is large)."""

    step: int
    tool_name: str
    arguments: dict[str, Any] | None
    is_error: bool
    error_code: str | None
    latency_ms: int


class MessageOut(BaseModel):
    message_id: int
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime
    # Assistant only: the structured answer (type, product_ids for the cards, suggested
    # replies...) and the tools used to produce it
    response: dict[str, Any] | None = None
    tools: list[ToolCallSummary] = []


class ConversationMessages(BaseModel):
    conversation_id: uuid.UUID
    title: str
    messages: list[MessageOut]


def _owned(session: Session, user_id: int, conversation_id: uuid.UUID) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    # Someone else's conversation looks exactly like a missing one (no info leak)
    if conversation is None or conversation.user_id != user_id:
        raise DomainError(
            "CONVERSATION_NOT_FOUND", "Conversation not found", {"id": str(conversation_id)}
        )
    return conversation


def list_conversations(
    session: Session, user_id: int, limit: int = 20, offset: int = 0
) -> ConversationList:
    """The user's conversations, most recent activity first."""
    if not 1 <= limit <= MAX_LIMIT or offset < 0:
        raise DomainError("INVALID_INPUT", f"limit between 1 and {MAX_LIMIT}, offset >= 0")

    stats = (
        select(
            ChatMessage.conversation_id,
            func.count().label("message_count"),
            func.max(ChatMessage.created_at).label("last_at"),
            func.max(ChatMessage.id).label("last_id"),
        )
        .group_by(ChatMessage.conversation_id)
        .subquery()
    )
    base = (
        select(Conversation, stats.c.message_count, stats.c.last_at, ChatMessage.content)
        .join(stats, stats.c.conversation_id == Conversation.id)
        .join(ChatMessage, ChatMessage.id == stats.c.last_id)
        .where(Conversation.user_id == user_id)
    )
    total = session.scalar(select(func.count()).select_from(base.subquery()))
    rows = session.execute(base.order_by(stats.c.last_id.desc()).limit(limit).offset(offset)).all()
    return ConversationList(
        items=[
            ConversationSummary(
                conversation_id=conversation.id,
                title=conversation.title,
                created_at=conversation.created_at,
                last_message_at=last_at,
                message_count=count,
                last_message_preview=content[:PREVIEW_LENGTH],
            )
            for conversation, count, last_at, content in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_messages(
    session: Session, user_id: int, conversation_id: uuid.UUID
) -> ConversationMessages:
    """Every message of one of the user's conversations, oldest first."""
    conversation = _owned(session, user_id, conversation_id)
    messages = session.scalars(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation.id)
        .order_by(ChatMessage.id)
    ).all()
    tools: dict[int, list[ToolCallSummary]] = {}
    for log in session.scalars(
        select(ToolCallLog)
        .where(ToolCallLog.message_id.in_([m.id for m in messages]))
        .order_by(ToolCallLog.message_id, ToolCallLog.step, ToolCallLog.id)
    ):
        error = log.result.get("error") if log.is_error else None
        tools.setdefault(log.message_id, []).append(
            ToolCallSummary(
                step=log.step,
                tool_name=log.tool_name,
                arguments=log.arguments,
                is_error=log.is_error,
                error_code=error.get("code") if isinstance(error, dict) else None,
                latency_ms=log.latency_ms,
            )
        )
    return ConversationMessages(
        conversation_id=conversation.id,
        title=conversation.title,
        messages=[
            MessageOut(
                message_id=m.id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                response=(m.structured or {}).get("response") if m.role == "assistant" else None,
                tools=tools.get(m.id, []),
            )
            for m in messages
        ],
    )
