"""FastAPI dependencies: the logged-in user comes from `Authorization: Bearer <token>`.
Tools never receive a user_id from the model: the backend injects it from here."""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.auth.service import user_for_token
from app.db import get_db
from app.domain.errors import DomainError
from app.models import User


def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise DomainError("UNAUTHORIZED", "Falta iniciar sesión")
    return token.strip()


def current_user(
    token: Annotated[str, Depends(bearer_token)], db: Annotated[Session, Depends(get_db)]
) -> User:
    return user_for_token(db, token)


CurrentUser = Annotated[User, Depends(current_user)]
