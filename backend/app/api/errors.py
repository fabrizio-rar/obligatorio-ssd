"""One place that turns DomainError into an HTTP response, with the uniform format
{"ok": false, "error": {"code", "message", "details"}} (AGENTS.md rule 7)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
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
    "NOT_IN_CART": 404,
    "USERNAME_TAKEN": 409,
    "INACTIVE": 409,
    "OUT_OF_STOCK": 409,
    "MIXED_CATEGORIES": 422,
    "CHAT_DISABLED": 503,
    "STT_DISABLED": 503,
    "UNSUPPORTED_AUDIO": 415,
    "AUDIO_TOO_LARGE": 413,
    "AUDIO_TOO_SHORT": 422,
    "NO_SPEECH": 422,
    "INVALID_AUDIO": 422,
    # Checkout and orders (docs/PLAN.md §12.1)
    "EMPTY_CART": 409,
    "CART_HAS_ISSUES": 409,
    "PICKUP_UNAVAILABLE": 409,
    "CART_CHANGED": 409,
    "PRICE_CHANGED": 409,
    "ORDER_NOT_FOUND": 404,
    "ORDER_CANCELLED": 409,
    "ORDER_NOT_CANCELLABLE": 409,
}


def _spanish(error: dict) -> str:
    """The user reads these messages (forms), so the common Pydantic ones go in Spanish.
    Our own validators already raise their message in Spanish ("Value error, ...")."""
    ctx = error.get("ctx") or {}
    match error["type"]:
        case "missing":
            return "Falta este dato"
        case "string_too_short":
            return f"Tiene que tener al menos {ctx.get('min_length')} caracteres"
        case "string_too_long":
            return f"Puede tener hasta {ctx.get('max_length')} caracteres"
        case "enum" | "literal_error":
            return "Valor no válido"
        case "extra_forbidden":
            return "Campo no permitido"
        case "int_parsing" | "decimal_parsing" | "float_parsing":
            return "Tiene que ser un número"
        case _:
            return str(error["msg"]).removeprefix("Value error, ")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_request: Request, error: DomainError) -> JSONResponse:
        status = STATUS_BY_CODE.get(error.code, 400)
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        return JSONResponse(error.to_dict(), status_code=status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, error: RequestValidationError) -> JSONResponse:
        """FastAPI's own 422 (body, query, path) in the same uniform format. `fields` says
        which field failed, so a form can show it next to the input."""
        fields = [
            {
                "field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path")),
                "message": _spanish(e),
            }
            for e in error.errors()
        ]
        body = DomainError(
            "INVALID_INPUT",
            fields[0]["message"] if fields else "Datos inválidos",
            {"fields": fields},
        ).to_dict()
        return JSONResponse(body, status_code=422)
