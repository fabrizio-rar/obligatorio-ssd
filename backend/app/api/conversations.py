"""The user's chat history (login required). New conversations are created by
POST /api/chat when it receives no conversation_id."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.agent import conversations
from app.agent.conversations import MAX_LIMIT, ConversationList, ConversationMessages
from app.auth.dependencies import CurrentUser
from app.db import get_db

router = APIRouter(prefix="/conversations", tags=["chat"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ConversationList)
def list_conversations(
    user: CurrentUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return conversations.list_conversations(db, user.id, limit=limit, offset=offset)


@router.get("/{conversation_id}/messages", response_model=ConversationMessages)
def messages(conversation_id: uuid.UUID, user: CurrentUser, db: Db):
    return conversations.get_messages(db, user.id, conversation_id)
