"""Public catalog endpoints against the real dataset."""

import pytest
from sqlalchemy import func, select

from app.models import Product

pytestmark = pytest.mark.integration

ACTIVE = 343  # 360 products - 17 inactive


def _id(db, name):
    return db.scalar(select(Product.id).where(Product.name == name))


def test_catalog_is_public_and_paginated(api):
    first = api.get("/api/products", params={"page_size": 50})
    assert first.status_code == 200
    body = first.json()
    assert body["total"] == ACTIVE
    assert body["total_pages"] == 7
    assert len(body["items"]) == 50
    card = body["items"][0]
    assert {
        "product_id",
        "name",
        "current_price",
        "list_price",
        "available",
        "stock_status",
        "image_url",
        "category",
    } <= set(card)

    seen = set()
    for page in range(1, 8):
        items = api.get("/api/products", params={"page": page, "page_size": 50}).json()["items"]
        seen.update(i["product_id"] for i in items)
    assert len(seen) == ACTIVE  # stable order: every product once


def test_inactive_products_are_never_listed(api, catalog_db):
    inactive = set(catalog_db.scalars(select(Product.id).where(Product.active.is_(False))))
    items = api.get("/api/products", params={"page_size": 60}).json()["items"]
    all_ids = {i["product_id"] for i in items}
    page = 2
    while True:
        more = api.get("/api/products", params={"page": page, "page_size": 60}).json()["items"]
        if not more:
            break
        all_ids |= {i["product_id"] for i in more}
        page += 1
    assert not all_ids & inactive


def test_filter_by_category(api, catalog_db):
    body = api.get("/api/products", params={"category": "Headphones", "page_size": 60}).json()
    expected = catalog_db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.id.like("MN-HDP-%"), Product.active.is_(True))
    )
    assert body["total"] == expected
    assert {i["category"] for i in body["items"]} == {"Headphones"}


@pytest.mark.parametrize(
    "params",
    [{"category": "Auriculares"}, {"page": 0}, {"page_size": 61}, {"ids": "a", "category": "Mice"}],
)
def test_invalid_listing_params(api, params):
    assert api.get("/api/products", params=params).status_code == 422


def test_page_past_the_end_is_empty(api):
    body = api.get("/api/products", params={"page": 99}).json()
    assert body["items"] == [] and body["total"] == ACTIVE


def test_cards_by_ids_keep_order_and_skip_inactive_or_unknown(api, catalog_db):
    a, b = _id(catalog_db, "Vector Air 690"), _id(catalog_db, "Orbit Sound 458")
    inactive = _id(catalog_db, "Cedar Air 243")
    body = api.get("/api/products", params={"ids": f"{b},{inactive},MN-XXX-0000,{a},{b}"}).json()
    assert [i["product_id"] for i in body["items"]] == [b, a]


def test_product_detail(api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    body = api.get(f"/api/products/{pid}").json()
    assert body["status"] == "available"
    assert len(body["stock_by_warehouse"]) == 5
    assert {s["name"] for s in body["specs"]} >= {"Active Noise Cancellation", "Battery Life"}
    for related in body["alternatives"] + body["accessories"] + body["often_bought_with"]:
        assert related["available"] > 0  # only sellable, in-stock related products


def test_accessories_point_the_right_way(api, catalog_db):
    laptop = _id(catalog_db, "Flux Edge 15 8/256")
    accessories = api.get(f"/api/products/{laptop}").json()["accessories"]
    assert accessories
    assert all(a["category"] != "Laptops" for a in accessories)  # webcams etc., never laptops
    strengths = [float(a["strength"]) for a in accessories]
    assert strengths == sorted(strengths, reverse=True)


def test_discontinued_detail(api, catalog_db):
    body = api.get(f"/api/products/{_id(catalog_db, 'Cedar Air 243')}").json()
    assert body["status"] == "discontinued"
    assert body["current_price"] is None and body["stock_by_warehouse"] == []
    assert body["accessories"] == []  # only alternatives, to offer something else


def test_unknown_product_is_404(api):
    response = api.get("/api/products/MN-XXX-0000")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_categories_and_warehouses(api):
    categories = api.get("/api/categories").json()
    assert len(categories) == 12
    headphones = next(c for c in categories if c["name"] == "Headphones")
    assert headphones["subcategories"] == ["Over-Ear", "On-Ear", "True Wireless"]
    assert sum(c["product_count"] for c in categories) == ACTIVE

    warehouses = api.get("/api/warehouses").json()
    assert {w["warehouse_id"] for w in warehouses} >= {"WH-COL-001", "WH-MVD-CEN"}
    assert len(warehouses) == 5
