"""Conversations with the assistant (docs/PLAN.md §7.2). No user yet: login arrives with N3."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Owner. Nullable only for conversations created before login existed (migration 0004)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)  # what goes back to the model as history
    structured: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # AgentResponse + meta
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="ck_chat_role"),)


class ToolCallLog(Base):
    """Which tools the agent used, with what arguments and what came back. Evidence of the
    multi-step behaviour for the report, and the future "ver tools usadas" panel."""

    __tablename__ = "tool_call_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), index=True
    )
    step: Mapped[int]
    tool_name: Mapped[str] = mapped_column(Text)
    arguments: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any]] = mapped_column(JSONB)
    is_error: Mapped[bool]
    latency_ms: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentStateRow(Base):
    __tablename__ = "agent_state"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
