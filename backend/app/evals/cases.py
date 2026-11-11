"""Eval cases (tests/evals/cases.json): loaded and validated before spending any credit."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.evals.checks import CHECKS

CASES_PATH = Path(__file__).resolve().parents[2] / "tests/evals/cases.json"


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str = Field(min_length=1)
    expect: dict[str, Any] = Field(default_factory=dict)  # checked after THIS turn

    @field_validator("expect")
    @classmethod
    def known_checks(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = sorted(set(value) - set(CHECKS))
        if unknown:
            raise ValueError(f"unknown expectations: {unknown}")
        return value


class Setup(BaseModel):
    """Prepared with the domain functions before the first turn (a fresh user per case)."""

    model_config = ConfigDict(extra="forbid")

    cart: list[tuple[str, int]] = Field(default_factory=list)  # (product name or ID, quantity)
    purchases: list[tuple[str, int]] = Field(default_factory=list)  # confirmed orders, 1 each


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    description: str
    setup: Setup = Field(default_factory=Setup)
    turns: list[Turn] = Field(min_length=1)


def load_cases(path: Path = CASES_PATH) -> list[Case]:
    cases = [Case.model_validate(c) for c in json.loads(path.read_text(encoding="utf-8"))]
    ids = [c.id for c in cases]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise ValueError(f"duplicated case ids: {duplicated}")
    return cases
