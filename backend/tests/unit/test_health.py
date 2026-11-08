from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import get_db
from app.main import app


class _FakeSession:
    def __init__(self, fail: bool):
        self.fail = fail

    def execute(self, *_args, **_kwargs):
        if self.fail:
            raise OperationalError("SELECT 1", {}, Exception("db down"))


def _client(fail: bool) -> TestClient:
    app.dependency_overrides[get_db] = lambda: _FakeSession(fail)
    return TestClient(app)


def teardown_function():
    app.dependency_overrides.clear()


def test_health_ok():
    response = _client(fail=False).get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["db"] == "ok"
    assert isinstance(response.json()["chat_enabled"], bool)


def test_health_reports_db_down():
    response = _client(fail=True).get("/api/health")
    assert response.status_code == 503
    body = response.json()
    assert (body["status"], body["db"]) == ("degraded", "unavailable")
    assert isinstance(body["chat_enabled"], bool) and isinstance(body["stt_enabled"], bool)
