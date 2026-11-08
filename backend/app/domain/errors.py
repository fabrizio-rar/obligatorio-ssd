"""Typed domain errors. They go back to the caller (API or agent tool) as data with the
format {"ok": false, "error": {"code", "message", "details"}}, never as raw exceptions."""

from typing import Any


class DomainError(Exception):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {"code": self.code, "message": self.message, "details": self.details},
        }
