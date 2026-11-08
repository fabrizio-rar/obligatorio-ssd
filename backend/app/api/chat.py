"""POST /api/chat: one turn with the assistant. Only HTTP here; the logic is in agent/."""

import uuid
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.llm.base import LLMError, LLMProvider
from app.agent.llm.factory import get_llm_provider
from app.agent.service import ChatTurn, chat_turn, error_body
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
    db: Annotated[Session, Depends(get_db)],
    llm: Annotated[LLMProvider | None, Depends(get_llm)],
    embedder: Annotated[Embedder | None, Depends(get_query_embedder)],
):
    message = request.message.strip()
    if not message:
        return JSONResponse(
            error_body("EMPTY_MESSAGE", "El mensaje está vacío"),
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    if llm is None:
        return JSONResponse(
            error_body("CHAT_DISABLED", "Asistente no disponible: falta configurar OPENAI_API_KEY"),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    try:
        return await chat_turn(db, llm, embedder, get_settings(), message, request.conversation_id)
    except DomainError as error:
        return JSONResponse(error.to_dict(), status_code=status.HTTP_404_NOT_FOUND)
    except LLMError as error:
        code = (
            status.HTTP_503_SERVICE_UNAVAILABLE if error.retryable else status.HTTP_502_BAD_GATEWAY
        )
        return JSONResponse(
            error_body(
                error.code,
                "El asistente no está disponible en este momento. Probá de nuevo en un rato."
                if error.retryable
                else "El asistente tuvo un error y no pudo responder.",
                {"retryable": error.retryable},
            ),
            status_code=code,
        )
