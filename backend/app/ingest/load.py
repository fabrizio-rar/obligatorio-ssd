"""Upsert the validated rows into Postgres, in dependency order, by natural key."""

from collections.abc import Iterator
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db import Base
from app.ingest.report import TableStats
from app.ingest.validate import CatalogData
from app.models import (
    Brand,
    Category,
    Inventory,
    Price,
    Product,
    ProductRelation,
    ProductSpec,
    Subcategory,
    Warehouse,
)

# Parent tables first so foreign keys always resolve
LOAD_ORDER: list[tuple[str, type[Base]]] = [
    ("brands", Brand),
    ("categories", Category),
    ("subcategories", Subcategory),
    ("products", Product),
    ("prices", Price),
    ("product_specs", ProductSpec),
    ("warehouses", Warehouse),
    ("inventory", Inventory),
    ("product_relations", ProductRelation),
]

BATCH_SIZE = 500  # keeps each INSERT well under Postgres' bind-parameter limit


def _batches(rows: list[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def _existing_keys(session: Session, model: type[Base]) -> set[tuple]:
    pk = list(model.__table__.primary_key.columns)
    return {tuple(row) for row in session.execute(select(*pk))}


def upsert_table(
    session: Session, model: type[Base], rows: list[dict[str, Any]], update_existing: bool
) -> TableStats:
    """Insert new rows; update existing ones (or leave them alone if update_existing=False)."""
    table = model.__table__
    pk_names = [c.name for c in table.primary_key.columns]
    # Generated columns (available_qty, search_tsv) are computed by Postgres
    updatable = [c.name for c in table.columns if c.name not in pk_names and c.computed is None]

    if not rows:
        return TableStats()

    existing = _existing_keys(session, model)
    keys = [tuple(row[name] for name in pk_names) for row in rows]
    already_there = sum(1 for key in keys if key in existing)
    stats = TableStats(rows=len(rows), inserted=len(rows) - already_there)
    if update_existing:
        stats.updated = already_there
    else:
        stats.skipped = already_there

    for batch in _batches(rows):
        stmt = insert(table).values(batch)
        if update_existing and updatable:
            stmt = stmt.on_conflict_do_update(
                index_elements=pk_names,
                set_={name: stmt.excluded[name] for name in updatable},
            )
        else:
            stmt = stmt.on_conflict_do_nothing(index_elements=pk_names)
        session.execute(stmt)
    return stats


def load_catalog(
    session: Session, data: CatalogData, reset_inventory: bool
) -> dict[str, TableStats]:
    """Load every table. Inventory is only overwritten with reset_inventory=True, so that
    stock consumed by purchases is not "undone" by a re-ingest (docs/PLAN.md §8)."""
    stats: dict[str, TableStats] = {}
    for name, model in LOAD_ORDER:
        update_existing = reset_inventory if model is Inventory else True
        stats[name] = upsert_table(session, model, getattr(data, name), update_existing)
    return stats


def catalog_is_empty(session: Session) -> bool:
    return session.execute(select(Product.id).limit(1)).first() is None
