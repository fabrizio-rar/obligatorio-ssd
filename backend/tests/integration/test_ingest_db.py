"""Ingest of the real dataset into a real Postgres."""

import copy

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.domain.catalog import EMPTY_SPEC_VALUE
from app.ingest.pipeline import ingest_records
from app.models import Inventory, Price, Product, ProductSpec
from tests.factories import make_records

pytestmark = pytest.mark.integration

EXPECTED_ROWS = {
    "brands": 20,
    "categories": 12,
    "subcategories": 37,
    "products": 360,
    "prices": 360,
    "product_specs": 3000,
    "warehouses": 5,
    "inventory": 1800,
    "product_relations": 1080,
}


def _count(session: Session, table: str) -> int:
    return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_full_dataset_is_loaded(session, dataset_records):
    report = ingest_records(session, dataset_records, "dataset")

    assert report.rejected == []
    for table, rows in EXPECTED_ROWS.items():
        assert _count(session, table) == rows, table
        assert report.tables[table].inserted == rows
    # Known data-quality findings (docs/PLAN.md §2.1)
    assert len(report.findings["inactive_products"]) == 17
    assert len(report.findings["out_of_stock_products"]) == 22
    assert len(report.findings["duplicate_names"]) == 3
    assert report.findings["empty_specs"] == 37
    nd_specs = session.scalar(
        select(func.count()).where(ProductSpec.value_text == EMPTY_SPEC_VALUE)
    )
    assert nd_specs == 37


def test_generated_columns_and_availability_view(session, dataset_records):
    ingest_records(session, dataset_records, "dataset")

    bad_available = session.scalar(
        select(func.count()).where(
            Inventory.available_qty != Inventory.on_hand_qty - Inventory.reserved_qty
        )
    )
    assert bad_available == 0

    rows = session.execute(
        text("SELECT status, count(*) FROM product_availability GROUP BY status")
    ).all()
    by_status = dict(rows)
    assert sum(by_status.values()) == 360
    assert by_status["Out of stock"] == 22

    matches = session.scalar(
        select(func.count()).where(
            Product.search_tsv.op("@@")(func.plainto_tsquery("english", "headphones"))
        )
    )
    assert matches > 0


def test_reingest_is_idempotent(session, dataset_records):
    ingest_records(session, dataset_records, "dataset")
    second = ingest_records(session, dataset_records, "dataset")

    for table, rows in EXPECTED_ROWS.items():
        assert _count(session, table) == rows, table
        assert second.tables[table].inserted == 0, table
    assert second.tables["products"].updated == 360
    assert second.tables["inventory"].skipped == 1800


def test_reingest_keeps_inventory_unless_reset(session, dataset_records):
    ingest_records(session, dataset_records, "dataset")
    row = session.execute(select(Inventory).where(Inventory.on_hand_qty > 0).limit(1)).scalar_one()
    key = (row.product_id, row.warehouse_id)
    original = row.on_hand_qty

    # Simulate a purchase consuming stock
    session.execute(
        update(Inventory)
        .where(Inventory.product_id == key[0], Inventory.warehouse_id == key[1])
        .values(on_hand_qty=Inventory.reserved_qty)
    )
    session.commit()

    def on_hand() -> int:
        session.expire_all()
        return session.get(Inventory, key).on_hand_qty

    ingest_records(session, dataset_records, "dataset")
    assert on_hand() != original  # purchase not "undone"

    ingest_records(session, dataset_records, "dataset", reset_inventory=True)
    assert on_hand() == original


def test_reingest_updates_changed_prices(session):
    records = make_records()
    ingest_records(session, records, "mini")

    changed = copy.deepcopy(records)
    changed["Pricing"][0].update(current_price=160.0, discount_percent=20)
    report = ingest_records(session, changed, "mini")

    session.expire_all()
    assert str(session.get(Price, "MN-HDP-0001").current_price) == "160.00"
    assert report.tables["prices"].updated == 2


def test_invalid_rows_are_skipped_but_the_rest_loads(session):
    records = make_records()
    records["Pricing"][0]["current_price"] = 1.0
    report = ingest_records(session, records, "mini")

    assert len(report.rejected) == 1
    assert _count(session, "products") == 2
    assert _count(session, "prices") == 1


def test_failure_mid_load_rolls_back_everything(session, monkeypatch):
    from app.ingest import load

    real_upsert = load.upsert_table

    def fail_on_prices(session_, model, rows, update_existing):
        if model is Price:  # brands, categories, ... products were already written
            raise RuntimeError("boom")
        return real_upsert(session_, model, rows, update_existing)

    monkeypatch.setattr(load, "upsert_table", fail_on_prices)
    with pytest.raises(RuntimeError):
        ingest_records(session, make_records(), "mini")
    assert _count(session, "brands") == 0
    assert _count(session, "products") == 0
