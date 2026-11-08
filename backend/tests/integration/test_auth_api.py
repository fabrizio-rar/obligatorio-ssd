"""Register / login / me / logout against the real DB."""

from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.auth.service import DEMO_PASSWORD, DEMO_USERNAME, _now, ensure_demo_user, hash_token
from app.models import AuthToken, User

pytestmark = pytest.mark.integration


def _creds(name, password="secret123"):
    return {"username": name, "password": password}


def test_register_login_me_logout(api, catalog_db):
    created = api.post("/api/auth/register", json=_creds("  Lucia "))
    assert created.status_code == 201
    assert created.json()["username"] == "lucia"  # normalized

    login = api.post("/api/auth/login", json=_creds("LUCIA"))  # case-insensitive
    assert login.status_code == 200
    body = login.json()
    assert body["user"]["username"] == "lucia"
    token = body["token"]
    headers = {"Authorization": f"Bearer {token}"}

    me = api.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["username"] == "lucia"

    # Only the hash is stored
    stored = catalog_db.scalars(select(AuthToken.token_hash)).all()
    assert hash_token(token) in stored and token not in stored

    assert api.post("/api/auth/logout", headers=headers).status_code == 204
    after = api.get("/api/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "UNAUTHORIZED"


def test_password_is_hashed(api, catalog_db):
    api.post("/api/auth/register", json=_creds("hashcheck"))
    user = catalog_db.scalar(select(User).where(User.username == "hashcheck"))
    assert user.password_hash.startswith("$2") and "secret123" not in user.password_hash


def test_duplicate_username_is_409(api):
    api.post("/api/auth/register", json=_creds("dupe"))
    again = api.post("/api/auth/register", json=_creds("DUPE"))
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "USERNAME_TAKEN"


def test_wrong_password_and_unknown_user_look_the_same(api):
    api.post("/api/auth/register", json=_creds("carla"))
    wrong = api.post("/api/auth/login", json=_creds("carla", "nope123"))
    unknown = api.post("/api/auth/login", json=_creds("nadie-existe"))
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # does not reveal which usernames exist


@pytest.mark.parametrize(
    "body",
    [_creds("ab"), _creds("valid_name", "123"), {"username": "x"}, {}],
)
def test_register_validation(api, body):
    response = api.post("/api/auth/register", json=body)
    assert response.status_code == 422


@pytest.mark.parametrize(
    "header", [None, "Bearer", "Bearer   ", "Basic abc", "Bearer not-a-real-token"]
)
def test_bad_or_missing_token_is_401(api, header):
    headers = {"Authorization": header} if header else {}
    response = api.get("/api/auth/me", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_is_401(api, catalog_db):
    token = api.login()
    catalog_db.execute(
        update(AuthToken)
        .where(AuthToken.token_hash == hash_token(token))
        .values(expires_at=_now() - timedelta(minutes=1))
    )
    catalog_db.commit()
    assert api.get("/api/auth/me").status_code == 401


def test_demo_user_seed_is_idempotent(api, catalog_db):
    first = ensure_demo_user(catalog_db)
    second = ensure_demo_user(catalog_db)
    assert second is False
    assert first in (True, False)  # may already exist from another test
    login = api.post("/api/auth/login", json=_creds(DEMO_USERNAME, DEMO_PASSWORD))
    assert login.status_code == 200
