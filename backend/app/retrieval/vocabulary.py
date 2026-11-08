"""Closed vocabulary of the catalog: categories, subcategories and use cases.

Read from JSON files (vocabulary_data/) so the values are easy to review and are not
scattered in the code. They become enums, which are the only values the agent can pass
to search_products (strict tool schema). An integration test checks that the JSON
matches the DB, so a dataset change cannot silently drift.
"""

import json
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Category as CategoryModel
from app.models import Product, Subcategory

DATA_DIR = Path(__file__).parent / "vocabulary_data"


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


SUBCATEGORIES: dict[str, list[str]] = _load("categories.json")
_USE_CASES = _load("use_cases.json")


def _enum(name: str, values: list[str]) -> type[StrEnum]:
    # Member names are only for Python; the value is the exact dataset string
    return StrEnum(name, {v.upper().replace(" ", "_").replace("-", "_"): v for v in values})


Category = _enum("Category", list(SUBCATEGORIES))
UseCase = _enum("UseCase", _USE_CASES["recommended_for"])
AvoidCase = _enum("AvoidCase", _USE_CASES["not_recommended_for"])


def subcategory_belongs(category: str, subcategory: str) -> bool:
    return subcategory in SUBCATEGORIES.get(category, [])


def use_case_categories(session: Session) -> dict[str, list[str]]:
    """In which categories each use case appears (active products only). Goes into the
    tool description so the model picks e.g. 'calls' (not 'video calls') for headphones."""
    rows = session.execute(
        select(Product.recommended_for, CategoryModel.name)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(CategoryModel, CategoryModel.id == Subcategory.category_id)
        .where(Product.active.is_(True))
    )
    result: dict[str, set[str]] = {}
    for uses, category in rows:
        for use in uses:
            result.setdefault(use, set()).add(category)
    return {use: sorted(cats) for use, cats in sorted(result.items())}
