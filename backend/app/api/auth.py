"""POST /api/auth/register, /login, /logout and GET /api/auth/me. Only HTTP here."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.dependencies import CurrentUser, bearer_token
from app.config import get_settings
from app.db import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    id: int
    username: str


class LoginOut(BaseModel):
    token: str
    token_type: str = "bearer"
    expires_in_hours: int
    user: UserOut


@router.post("/register", status_code=status.HTTP_201_CREATED, response_model=UserOut)
def register(body: Credentials, db: Annotated[Session, Depends(get_db)]):
    user = service.register(db, body.username, body.password)
    return UserOut(id=user.id, username=user.username)


@router.post("/login", response_model=LoginOut)
def login(body: Credentials, db: Annotated[Session, Depends(get_db)]):
    ttl = get_settings().auth_token_ttl_hours
    token, user = service.login(db, body.username, body.password, ttl)
    return LoginOut(
        token=token, expires_in_hours=ttl, user=UserOut(id=user.id, username=user.username)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    _user: CurrentUser,
    token: Annotated[str, Depends(bearer_token)],
    db: Annotated[Session, Depends(get_db)],
):
    service.logout(db, token)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser):
    return UserOut(id=user.id, username=user.username)
