"""Users and session tokens (docs/PLAN.md §7.2): simple login, as the assignment asks."""

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)  # stored lowercase
    password_hash: Mapped[str] = mapped_column(Text)  # bcrypt
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AuthToken(Base):
    """Opaque session token. Only its SHA-256 is stored: someone who reads the DB
    cannot use the tokens to impersonate users. Logout = delete the row."""

    __tablename__ = "auth_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
