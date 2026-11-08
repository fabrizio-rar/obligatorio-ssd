"""POST /api/transcribe: audio -> text (login required). It does NOT talk to the agent:
the UI puts the text in the chat input, the user edits it and sends it to /api/chat."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.config import get_settings
from app.db import get_db
from app.domain.errors import DomainError
from app.stt.transcriber import (
    SUPPORTED_AUDIO,
    Transcriber,
    TranscriptionError,
    get_transcriber,
    vocabulary_prompt,
)

router = APIRouter(tags=["voice"])

MIN_AUDIO_BYTES = 1000  # below this there is no real speech (just a header / a click)


class TranscriptionOut(BaseModel):
    text: str
    model: str


@lru_cache
def get_stt() -> Transcriber | None:
    return get_transcriber(get_settings())


@router.post("/transcribe", response_model=TranscriptionOut)
async def transcribe(
    _user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    stt: Annotated[Transcriber | None, Depends(get_stt)],
    file: Annotated[UploadFile, File(description="Recorded audio (webm, ogg, mp4/m4a, mp3, wav)")],
):
    if stt is None:
        raise DomainError(
            "STT_DISABLED", "La voz no está disponible: falta configurar OPENAI_API_KEY"
        )
    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in SUPPORTED_AUDIO:
        raise DomainError(
            "UNSUPPORTED_AUDIO",
            "Formato de audio no soportado",
            {"content_type": content_type, "supported": sorted(SUPPORTED_AUDIO)},
        )
    max_bytes = get_settings().stt_max_bytes
    audio = await file.read(max_bytes + 1)  # never read more than the limit
    if len(audio) > max_bytes:
        raise DomainError(
            "AUDIO_TOO_LARGE",
            "El audio es demasiado largo (máximo 30 segundos)",
            {"max_bytes": max_bytes},
        )
    if len(audio) < MIN_AUDIO_BYTES:
        raise DomainError("AUDIO_TOO_SHORT", "El audio está vacío o es demasiado corto")

    try:
        result = await stt.transcribe(audio, content_type, prompt=vocabulary_prompt(db))
    except TranscriptionError as error:
        if error.code == "INVALID_AUDIO":
            raise DomainError(
                "INVALID_AUDIO", "No se pudo leer el audio. Probá grabar de nuevo."
            ) from error
        return JSONResponse(
            DomainError(
                error.code,
                "La transcripción no está disponible en este momento. Probá de nuevo en un rato."
                if error.retryable
                else "La transcripción tuvo un error.",
                {"retryable": error.retryable},
            ).to_dict(),
            status_code=503 if error.retryable else 502,
        )
    if not result.text:
        raise DomainError("NO_SPEECH", "No se entendió nada. Probá hablar más cerca del micrófono.")
    return TranscriptionOut(text=result.text, model=result.model)
