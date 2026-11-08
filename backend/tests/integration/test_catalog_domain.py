"""domain/catalog.py against the real dataset: name lookup and product detail."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.catalog import (
    EMPTY_SPEC_VALUE,
    ProductStatus,
    find_products_by_name,
    get_product_detail,
)
from app.domain.errors import DomainError
from app.models import Product, ProductSpec

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    return catalog_db


def _id(db, name):
    return db.scalar(select(Product.id).where(Product.name == name))


def test_exact_name_ignores_case_and_spaces(db):
    matches = find_products_by_name(db, "  vector   AIR 690 ")
    assert [m.name for m in matches] == ["Vector Air 690"]


def test_partial_name_matches_every_word(db):
    matches = find_products_by_name(db, "Vector 690")
    assert "Vector Air 690" in [m.name for m in matches]
    assert all("vector" in m.name.lower() and "690" in m.name for m in matches)


def test_duplicate_names_return_both(db):
    matches = find_products_by_name(db, "Kairo Drive Pro 2TB")
    assert len(matches) == 2
    assert len({m.sku for m in matches}) == 2


def test_inactive_products_are_found_by_name(db):
    matches = find_products_by_name(db, "Cedar Air 243")
    assert [(m.name, m.active, m.category) for m in matches] == [
        ("Cedar Air 243", False, "Headphones")
    ]


def test_unknown_or_empty_name(db):
    assert find_products_by_name(db, "Producto Que No Existe 9000") == []
    assert find_products_by_name(db, "   ") == []
    # LIKE wildcards are escaped: unescaped, "_%_" would match every name
    assert find_products_by_name(db, "_%_") == []
    # ...and a literal % still works ("Aether Keys Pro 75%" exists)
    assert "Aether Keys Pro 75%" in [m.name for m in find_products_by_name(db, "75%")]


def test_detail_has_price_specs_and_stock_per_warehouse(db):
    detail = get_product_detail(db, _id(db, "Vector Air 690"))

    assert detail.status == ProductStatus.AVAILABLE
    assert detail.current_price is not None and detail.currency == "USD"
    by_wh = {w.warehouse_id: w.available for w in detail.stock_by_warehouse}
    assert by_wh["WH-COL-001"] == 0  # the eval case: nothing to pick up in Colonia
    assert by_wh["WH-MVD-EST"] == 6
    total = db.scalar(
        text("SELECT available FROM product_availability WHERE product_id = :id"),
        {"id": detail.product_id},
    )
    assert detail.available == total == sum(by_wh.values())
    specs = {s.name: s.value for s in detail.specs}
    assert specs["Active Noise Cancellation"] == "No"
    assert specs["Battery Life"] == "28 h"
    assert detail.warranty_months is not None and detail.dimensions_cm


def test_out_of_stock_status(db):
    detail = get_product_detail(db, _id(db, "Nimbus Sound 691"))
    assert detail.status == ProductStatus.OUT_OF_STOCK
    assert detail.available == 0
    assert detail.current_price is not None  # still sold, just no stock now


def test_discontinued_detail_has_no_price_or_stock(db):
    detail = get_product_detail(db, _id(db, "Cedar Air 243"))
    assert detail.status == ProductStatus.DISCONTINUED
    assert detail.category == "Headphones"  # enough to offer alternatives
    assert detail.current_price is None
    assert detail.available is None
    assert detail.stock_by_warehouse == []


def test_empty_specs_are_flagged_not_inferred(db):
    pid = db.scalar(
        select(ProductSpec.product_id)
        .join(Product)
        .where(ProductSpec.value_text == EMPTY_SPEC_VALUE, Product.active.is_(True))
        .limit(1)
    )
    detail = get_product_detail(db, pid)
    empty = [s for s in detail.specs if not s.available]
    assert empty and all(s.value == EMPTY_SPEC_VALUE for s in empty)


def test_unknown_product_id(db):
    with pytest.raises(DomainError) as info:
        get_product_detail(db, "MN-XXX-0000")
    assert info.value.code == "NOT_FOUND"
