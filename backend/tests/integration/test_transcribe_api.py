"""POST /api/transcribe with FakeTranscriber (no OpenAI)."""

import pytest

from app.api.transcribe import MIN_AUDIO_BYTES, get_stt
from app.main import app
from app.stt.transcriber import FakeTranscriber

pytestmark = pytest.mark.integration

AUDIO = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000  # bytes are not decoded by the fake


def _post(api, data=AUDIO, content_type="audio/webm;codecs=opus", filename="voz.webm"):
    return api.post("/api/transcribe", files={"file": (filename, data, content_type)})


@pytest.fixture
def stt(api):
    fake = FakeTranscriber("Busco auriculares para videollamadas, máximo 200 dólares")
    app.dependency_overrides[get_stt] = lambda: fake
    api.login()
    return fake


def test_transcribes_to_text(api, stt):
    response = _post(api)
    assert response.status_code == 200
    assert response.json() == {
        "text": "Busco auriculares para videollamadas, máximo 200 dólares",
        "model": "fake-stt",
    }
    call = stt.calls[0]
    assert call["content_type"] == "audio/webm"  # ";codecs=opus" removed
    assert call["bytes"] == len(AUDIO)
    assert "Nimbus" in call["prompt"] and "MercaNova" in call["prompt"]  # catalog vocabulary
    assert "Sound" in call["prompt"] and "Quiet" in call["prompt"]  # product lines too


def test_the_text_then_goes_to_the_chat_like_any_message(api, stt):
    """Voice is only another way to type: the transcription is plain text for /api/chat."""
    text = _post(api).json()["text"]
    assert isinstance(text, str) and text


def test_requires_login(api):
    app.dependency_overrides[get_stt] = lambda: FakeTranscriber()
    assert _post(api).status_code == 401


def test_disabled_without_key(api):
    app.dependency_overrides[get_stt] = lambda: None
    api.login()
    response = _post(api)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STT_DISABLED"


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"content_type": "text/plain", "filename": "x.txt"}, 415, "UNSUPPORTED_AUDIO"),
        ({"content_type": "image/png", "filename": "x.png"}, 415, "UNSUPPORTED_AUDIO"),
        ({"data": b"\x00" * (MIN_AUDIO_BYTES - 1)}, 422, "AUDIO_TOO_SHORT"),
        ({"data": b""}, 422, "AUDIO_TOO_SHORT"),
        ({"data": b"\x00" * 2_000_001}, 413, "AUDIO_TOO_LARGE"),
    ],
)
def test_invalid_uploads(api, stt, kwargs, status, code):
    response = _post(api, **kwargs)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert stt.calls == []  # never reaches the transcriber


def test_silence_is_reported(api):
    app.dependency_overrides[get_stt] = lambda: FakeTranscriber(text="")
    api.login()
    response = _post(api)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NO_SPEECH"


def test_missing_file_is_422(api, stt):
    assert api.post("/api/transcribe").status_code == 422
