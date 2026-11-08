"""Speech to text behind one interface (docs/PLAN.md §11).

- OpenAITranscriber: OpenAI transcription API (gpt-4o-transcribe by default).
- FakeTranscriber: scripted text for tests. Never calls the network.

The transcription only fills the chat input: the user edits it and sends it to
POST /api/chat like any typed message. No agent logic lives here.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import openai
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Brand, Product

# content type (without ";codecs=...") -> file extension. OpenAI infers the format
# from the file name, so the extension must match what the browser recorded.
SUPPORTED_AUDIO = {
    "audio/webm": "webm",  # Chrome / Firefox MediaRecorder
    "video/webm": "webm",  # some browsers label audio-only recordings like this
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",  # Safari MediaRecorder
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
}


class TranscriptionError(Exception):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class Transcription:
    text: str
    model: str


class Transcriber(Protocol):
    model: str

    async def transcribe(
        self, audio: bytes, content_type: str, prompt: str | None = None
    ) -> Transcription: ...


def vocabulary_prompt(session: Session) -> str:
    """Catalog words that a generic model may misspell (brands, the store name).
    The API uses it as context, not as an instruction."""
    brands = ", ".join(session.scalars(select(Brand.name).order_by(Brand.name)))
    # Product names are "<Brand> <Line> <number>" (e.g. "Nimbus Sound 691"): without the
    # line words the model writes "Nimbuson" or "Nimbus Zoom"
    line = func.split_part(Product.name, " ", 2)
    lines = ", ".join(
        session.scalars(select(line).where(Product.active.is_(True)).distinct().order_by(line))
    )
    return (
        "Conversación de compras en MercaNova, una tienda de electrónica en Uruguay. "
        f"Marcas: {brands}. Líneas de producto: {lines}. Los modelos se nombran como "
        "'Nimbus Sound 691' o 'Vector Air 690'. Productos como auriculares, monitores, "
        "laptops, mouse, teclados, webcams, parlantes, routers, impresoras, tablets y SSD."
    )


class OpenAITranscriber:
    def __init__(
        self,
        api_key: str,
        model: str,
        language: str = "es",
        timeout: float = 60,
        max_retries: int = 2,
        client: Any = None,  # injectable for tests
    ) -> None:
        self.model = model
        self.language = language
        self._client = client or openai.AsyncOpenAI(
            api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    async def transcribe(
        self, audio: bytes, content_type: str, prompt: str | None = None
    ) -> Transcription:
        extension = SUPPORTED_AUDIO[content_type]
        try:
            result = await self._client.audio.transcriptions.create(
                file=(f"audio.{extension}", audio, content_type),
                model=self.model,
                language=self.language,
                prompt=prompt or openai.omit,
                response_format="json",
            )
        except openai.AuthenticationError as error:
            raise TranscriptionError("AUTH", "OpenAI rejected the API key (401)", False) from error
        except openai.BadRequestError as error:
            # Typically: the file is not a valid audio for the API
            raise TranscriptionError(
                "INVALID_AUDIO", f"OpenAI could not read the audio: {error}", False
            ) from error
        except (
            openai.RateLimitError,
            openai.APIConnectionError,  # includes timeouts
            openai.InternalServerError,
        ) as error:
            raise TranscriptionError(
                "UNAVAILABLE", f"OpenAI transcription unavailable: {error}", True
            ) from error
        return Transcription(text=(result.text or "").strip(), model=self.model)


class FakeTranscriber:
    model = "fake-stt"

    def __init__(self, text: str = "busco auriculares para videollamadas") -> None:
        self.text = text
        self.calls: list[dict[str, Any]] = []

    async def transcribe(
        self, audio: bytes, content_type: str, prompt: str | None = None
    ) -> Transcription:
        self.calls.append({"bytes": len(audio), "content_type": content_type, "prompt": prompt})
        return Transcription(text=self.text, model=self.model)


def get_transcriber(settings: Settings) -> Transcriber | None:
    """None without OPENAI_API_KEY: voice is disabled, the rest of the app works."""
    if settings.stt_provider == "fake":
        return FakeTranscriber()
    if not settings.openai_configured:
        return None
    return OpenAITranscriber(
        api_key=settings.openai_api_key.get_secret_value(),
        model=settings.stt_model,
        language=settings.stt_language,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
