"""One place that turns DomainError into an HTTP response, with the uniform format
{"ok": false, "error": {"code", "message", "details"}} (AGENTS.md rule 7)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.domain.errors import DomainError

STATUS_BY_CODE = {
    "INVALID_INPUT": 422,
    "INVALID_ARGUMENTS": 422,
    "EMPTY_MESSAGE": 422,
    "UNAUTHORIZED": 401,
    "INVALID_CREDENTIALS": 401,
    "NOT_FOUND": 404,
    "CONVERSATION_NOT_FOUND": 404,
    "USERNAME_TAKEN": 409,
    "CHAT_DISABLED": 503,
}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError) -> JSONResponse:
        status = STATUS_BY_CODE.get(error.code, 400)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(error.to_dict(), status_code=status, headers=headers)
