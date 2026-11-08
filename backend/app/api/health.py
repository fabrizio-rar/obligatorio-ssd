"""Healthcheck: is the API up, can it reach the DB, is the chat configured."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Annotated[Session, Depends(get_db)], response: Response) -> dict:
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError:
        db_status = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "chat_enabled": get_settings().chat_enabled,
    }
