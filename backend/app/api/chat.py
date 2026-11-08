"""POST /api/chat: one turn with the assistant (requires login). Only HTTP here."""

import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMError, LLMProvider
from app.agent.llm.factory import get_llm_provider
from app.agent.service import ChatTurn, chat_turn
from app.auth.dependencies import CurrentUser
from app.config import get_settings
from app.db import get_db
from app.domain.errors import DomainError
from app.retrieval.embeddings import Embedder, get_embedder

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


@lru_cache
def get_llm() -> LLMProvider | None:
    return get_llm_provider(get_settings())


@lru_cache
def get_query_embedder() -> Embedder | None:
    return get_embedder(get_settings())


@router.post("/chat", response_model=ChatTurn)
async def chat(
    request: ChatRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    llm: Annotated[LLMProvider | None, Depends(get_llm)],
    embedder: Annotated[Embedder | None, Depends(get_query_embedder)],
):
    message = request.message.strip()
    if not message:
        raise DomainError("EMPTY_MESSAGE", "El mensaje está vacío")
    if llm is None:
        raise DomainError(
            "CHAT_DISABLED", "Asistente no disponible: falta configurar OPENAI_API_KEY"
        )
    try:
        return await chat_turn(
            db, llm, embedder, get_settings(), message, request.conversation_id, user_id=user.id
        )
    except LLMError as error:
        retryable = error.retryable
        body = DomainError(
            error.code,
            "El asistente no está disponible en este momento. Probá de nuevo en un rato."
            if retryable
            else "El asistente tuvo un error y no pudo responder.",
            {"retryable": retryable},
        ).to_dict()
        code = status.HTTP_503_SERVICE_UNAVAILABLE if retryable else status.HTTP_502_BAD_GATEWAY
        return JSONResponse(body, status_code=code)
