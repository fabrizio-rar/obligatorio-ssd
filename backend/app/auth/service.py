"""Register, login, logout and token resolution (docs/PLAN.md §4: user + password +
opaque token). Pure business logic: no HTTP here."""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

import bcrypt
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.models import AuthToken, User

USERNAME_PATTERN = re.compile(r"^[a-z0-9._-]{3,30}$")
PASSWORD_MIN = 6
PASSWORD_MAX_BYTES = 72  # bcrypt only uses the first 72 bytes: reject longer ones
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo1234"  # public demo account, documented in AGENTS.md / PLAN.md


def invalid_credentials() -> DomainError:
    # Same message for unknown user and wrong password: do not reveal which usernames exist
    return DomainError("INVALID_CREDENTIALS", "Usuario o contraseña incorrectos")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_credentials(username: str, password: str) -> str:
    """Returns the normalized username or raises INVALID_INPUT."""
    name = normalize_username(username)
    if not USERNAME_PATTERN.match(name):
        raise DomainError(
            "INVALID_INPUT",
            "El usuario debe tener entre 3 y 30 caracteres: letras, números, '.', '_' o '-'",
            {"field": "username"},
        )
    if len(password) < PASSWORD_MIN:
        raise DomainError(
            "INVALID_INPUT",
            f"La contraseña debe tener al menos {PASSWORD_MIN} caracteres",
            {"field": "password"},
        )
    if len(password.encode()) > PASSWORD_MAX_BYTES:
        raise DomainError(
            "INVALID_INPUT", "La contraseña es demasiado larga", {"field": "password"}
        )
    return name


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:  # malformed hash or password too long
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    # Naive UTC, like the DB columns (DateTime without time zone)
    return datetime.now(UTC).replace(tzinfo=None)


def register(session: Session, username: str, password: str) -> User:
    name = validate_credentials(username, password)
    if session.scalar(select(User.id).where(User.username == name)) is not None:
        raise DomainError("USERNAME_TAKEN", "Ese usuario ya existe", {"username": name})
    user = User(username=name, password_hash=hash_password(password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError as error:  # two registrations at the same time
        session.rollback()
        raise DomainError("USERNAME_TAKEN", "Ese usuario ya existe", {"username": name}) from error
    return user


def login(session: Session, username: str, password: str, ttl_hours: int) -> tuple[str, User]:
    """Returns (raw token, user). The raw token is only shown here, once."""
    user = session.scalar(select(User).where(User.username == normalize_username(username)))
    if user is None or not verify_password(password, user.password_hash):
        raise invalid_credentials()
    token = secrets.token_urlsafe(32)
    session.add(
        AuthToken(
            token_hash=hash_token(token),
            user_id=user.id,
            expires_at=_now() + timedelta(hours=ttl_hours),
        )
    )
    # Housekeeping: drop this user's expired tokens
    session.execute(
        delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.expires_at <= _now())
    )
    session.commit()
    return token, user


def user_for_token(session: Session, token: str) -> User:
    """Raises UNAUTHORIZED if the token does not exist or expired."""
    row = session.get(AuthToken, hash_token(token))
    if row is None or row.expires_at <= _now():
        raise DomainError("UNAUTHORIZED", "Sesión inválida o vencida: iniciá sesión de nuevo")
    return session.get(User, row.user_id)


def logout(session: Session, token: str) -> None:
    session.execute(delete(AuthToken).where(AuthToken.token_hash == hash_token(token)))
    session.commit()


def ensure_demo_user(session: Session) -> bool:
    """Creates demo / demo1234 if missing. Returns True if it was created."""
    if session.scalar(select(User.id).where(User.username == DEMO_USERNAME)) is not None:
        return False
    register(session, DEMO_USERNAME, DEMO_PASSWORD)
    return True
