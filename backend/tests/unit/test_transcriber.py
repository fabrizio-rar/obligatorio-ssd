import asyncio
from types import SimpleNamespace

import httpx2
import openai
import pytest

from app.config import Settings
from app.stt.transcriber import (
    FakeTranscriber,
    OpenAITranscriber,
    TranscriptionError,
    get_transcriber,
)

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/audio/transcriptions")


class FakeTranscriptions:
    def __init__(self, text="  busco auriculares  ", error=None):
        self.text, self.error, self.calls = text, error, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text)


def _transcriber(**kwargs):
    transcriptions = FakeTranscriptions(**kwargs)
    client = SimpleNamespace(audio=SimpleNamespace(transcriptions=transcriptions))
    return OpenAITranscriber(
        "k", "gpt-4o-mini-transcribe", language="es", client=client
    ), transcriptions


def test_sends_model_language_prompt_and_a_matching_file_name():
    stt, api = _transcriber()
    result = asyncio.run(stt.transcribe(b"x" * 2000, "audio/webm", prompt="Marcas: Nimbus"))

    call = api.calls[0]
    assert call["model"] == "gpt-4o-mini-transcribe"
    assert call["language"] == "es"
    assert call["prompt"] == "Marcas: Nimbus"
    name, audio, content_type = call["file"]
    assert name == "audio.webm" and content_type == "audio/webm" and len(audio) == 2000
    assert result.text == "busco auriculares"  # trimmed
    assert result.model == "gpt-4o-mini-transcribe"


@pytest.mark.parametrize(
    ("content_type", "ext"),
    [("audio/mp4", "mp4"), ("audio/mpeg", "mp3"), ("audio/x-wav", "wav"), ("video/webm", "webm")],
)
def test_extension_follows_the_content_type(content_type, ext):
    stt, api = _transcriber()
    asyncio.run(stt.transcribe(b"x" * 2000, content_type))
    assert api.calls[0]["file"][0] == f"audio.{ext}"


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (
            openai.AuthenticationError(
                "x", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            "AUTH",
            False,
        ),
        (
            openai.BadRequestError("x", response=httpx2.Response(400, request=REQUEST), body=None),
            "INVALID_AUDIO",
            False,
        ),
        (
            openai.RateLimitError("x", response=httpx2.Response(429, request=REQUEST), body=None),
            "UNAVAILABLE",
            True,
        ),
        (openai.APIConnectionError(request=REQUEST), "UNAVAILABLE", True),
    ],
)
def test_api_errors_are_mapped(error, code, retryable):
    stt, _ = _transcriber(error=error)
    with pytest.raises(TranscriptionError) as info:
        asyncio.run(stt.transcribe(b"x" * 2000, "audio/webm"))
    assert (info.value.code, info.value.retryable) == (code, retryable)


def _settings(**overrides) -> Settings:
    return Settings(database_url="postgresql+psycopg://x@y/z", **overrides)


def test_factory():
    assert get_transcriber(_settings(openai_api_key=None)) is None
    assert isinstance(get_transcriber(_settings(openai_api_key="sk-test")), OpenAITranscriber)
    assert isinstance(
        get_transcriber(_settings(stt_provider="fake", openai_api_key=None)), FakeTranscriber
    )
