"""Cart endpoints + domain/cart.py against the real dataset."""

from contextlib import contextmanager
from decimal import Decimal

import pytest
from sqlalchemy import select, update

from app.domain.cart import MAX_QUANTITY_PER_ITEM
from app.models import Inventory, Price, Product
from app.models.catalog import product_availability

pytestmark = pytest.mark.integration


def _id(db, name: str) -> str:
    return db.scalar(select(Product.id).where(Product.name == name))


def _add(api, product_id, quantity=1):
    return api.post("/api/cart/items", json={"product_id": product_id, "quantity": quantity})


@contextmanager
def _available(db, product_id: str, units: int):
    """Temporarily leave exactly `units` available for a product (restored afterwards)."""
    rows = db.scalars(select(Inventory).where(Inventory.product_id == product_id)).all()
    saved = {(r.warehouse_id): r.reserved_qty for r in rows}
    left = units
    for row in rows:
        keep = min(left, row.on_hand_qty)
        row.reserved_qty = row.on_hand_qty - keep
        left -= keep
    db.commit()
    try:
        yield
    finally:
        for row in rows:
            row.reserved_qty = saved[row.warehouse_id]
        db.commit()


@pytest.fixture
def cart_api(api):
    api.login()
    return api


def test_new_user_has_an_empty_cart(cart_api):
    body = cart_api.get("/api/cart").json()
    assert body == {
        "items": [],
        "item_count": 0,
        "currency": "USD",
        "total": "0.00",
        "can_checkout": False,
    }


def test_add_sums_quantities_and_computes_totals(cart_api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    price = catalog_db.get(Price, pid).current_price

    first = _add(cart_api, pid).json()
    assert first["item_count"] == 1 and first["can_checkout"] is True
    body = _add(cart_api, pid, 2).json()

    [item] = body["items"]
    assert item["quantity"] == 3
    assert Decimal(item["unit_price"]) == price
    assert Decimal(item["line_total"]) == price * 3
    assert Decimal(body["total"]) == price * 3
    assert body["item_count"] == 3
    assert item["issues"] == []


def test_several_products(cart_api, catalog_db):
    a, b = _id(catalog_db, "Vector Air 690"), _id(catalog_db, "Orbit Sound 458")
    _add(cart_api, a)
    body = _add(cart_api, b, 2).json()
    assert [i["product_id"] for i in body["items"]] == [a, b]  # in the order they were added
    expected = sum(Decimal(i["unit_price"]) * i["quantity"] for i in body["items"])
    assert Decimal(body["total"]) == expected
    assert body["item_count"] == 3


def test_cannot_add_out_of_stock_inactive_or_unknown(cart_api, catalog_db):
    no_stock = _add(cart_api, _id(catalog_db, "Nimbus Sound 691"))
    assert no_stock.status_code == 409
    assert no_stock.json()["error"]["code"] == "OUT_OF_STOCK"
    assert no_stock.json()["error"]["details"]["available"] == 0

    inactive = _add(cart_api, _id(catalog_db, "Cedar Air 243"))  # inactive, WITH stock
    assert inactive.status_code == 409
    assert inactive.json()["error"]["code"] == "INACTIVE"

    unknown = _add(cart_api, "MN-XXX-0000")
    assert unknown.status_code == 404
    assert cart_api.get("/api/cart").json()["items"] == []


def test_cannot_exceed_total_stock(cart_api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    with _available(catalog_db, pid, 2):
        assert _add(cart_api, pid, 2).status_code == 200
        response = _add(cart_api, pid, 1)  # 2 already in the cart + 1 > 2
        assert response.status_code == 409
        details = response.json()["error"]["details"]
        assert (details["available"], details["in_cart"]) == (2, 2)
        assert "Solo hay 2" in response.json()["error"]["message"]


@pytest.mark.parametrize("quantity", [0, -1, MAX_QUANTITY_PER_ITEM + 1, "dos"])
def test_invalid_quantities(cart_api, catalog_db, quantity):
    response = _add(cart_api, _id(catalog_db, "Vector Air 690"), quantity)
    assert response.status_code == 422


def test_max_quantity_counts_what_is_already_in_the_cart(cart_api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")  # 13 available: the limit (10) triggers first
    _add(cart_api, pid, 6)
    response = _add(cart_api, pid, 5)
    assert response.status_code == 422
    assert response.json()["error"]["details"]["in_cart"] == 6


def test_set_quantity(cart_api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    _add(cart_api, pid, 3)
    body = cart_api.patch(f"/api/cart/items/{pid}", json={"quantity": 1}).json()
    assert body["items"][0]["quantity"] == 1

    with _available(catalog_db, pid, 2):
        over = cart_api.patch(f"/api/cart/items/{pid}", json={"quantity": 3})
        assert over.status_code == 409
    assert cart_api.patch(f"/api/cart/items/{pid}", json={"quantity": 0}).status_code == 422

    other = cart_api.patch(
        f"/api/cart/items/{_id(catalog_db, 'Orbit Sound 458')}", json={"quantity": 1}
    )
    assert other.status_code == 404
    assert other.json()["error"]["code"] == "NOT_IN_CART"


def test_remove_and_clear(cart_api, catalog_db):
    a, b = _id(catalog_db, "Vector Air 690"), _id(catalog_db, "Orbit Sound 458")
    _add(cart_api, a)
    _add(cart_api, b)

    body = cart_api.delete(f"/api/cart/items/{a}").json()
    assert [i["product_id"] for i in body["items"]] == [b]
    assert cart_api.delete(f"/api/cart/items/{a}").status_code == 404  # already removed

    cleared = cart_api.delete("/api/cart").json()
    assert cleared["items"] == [] and cleared["can_checkout"] is False
    assert cart_api.delete("/api/cart").status_code == 200  # clearing twice is fine


def test_price_is_always_the_current_one(cart_api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    _add(cart_api, pid, 2)
    original = catalog_db.get(Price, pid).current_price
    catalog_db.execute(update(Price).where(Price.product_id == pid).values(current_price=50))
    catalog_db.commit()
    try:
        item = cart_api.get("/api/cart").json()["items"][0]
        assert Decimal(item["unit_price"]) == 50
        assert Decimal(item["line_total"]) == 100
    finally:
        catalog_db.execute(
            update(Price).where(Price.product_id == pid).values(current_price=original)
        )
        catalog_db.commit()


def test_product_deactivated_after_adding_is_flagged_not_removed(cart_api, catalog_db):
    a, b = _id(catalog_db, "Vector Air 690"), _id(catalog_db, "Orbit Sound 458")
    _add(cart_api, a)
    _add(cart_api, b)
    catalog_db.execute(update(Product).where(Product.id == a).values(active=False))
    catalog_db.commit()
    try:
        body = cart_api.get("/api/cart").json()
        flagged = next(i for i in body["items"] if i["product_id"] == a)
        assert flagged["issues"] == ["INACTIVE"]
        assert flagged["line_total"] == "0.00"
        assert body["can_checkout"] is False
        assert Decimal(body["total"]) == Decimal(
            next(i for i in body["items"] if i["product_id"] == b)["line_total"]
        )
        # It cannot be changed, only removed
        assert cart_api.patch(f"/api/cart/items/{a}", json={"quantity": 2}).status_code == 409
        after = cart_api.delete(f"/api/cart/items/{a}").json()
        assert after["can_checkout"] is True
    finally:
        catalog_db.execute(update(Product).where(Product.id == a).values(active=True))
        catalog_db.commit()


def test_stock_that_drops_after_adding_is_flagged(cart_api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    _add(cart_api, pid, 3)
    with _available(catalog_db, pid, 1):
        item = cart_api.get("/api/cart").json()["items"][0]
        assert item["issues"] == ["INSUFFICIENT_STOCK"] and item["available"] == 1
    with _available(catalog_db, pid, 0):
        body = cart_api.get("/api/cart").json()
        assert body["items"][0]["issues"] == ["OUT_OF_STOCK"]
        assert body["can_checkout"] is False
    available = catalog_db.scalar(
        select(product_availability.c.available).where(product_availability.c.product_id == pid)
    )
    assert available == 13  # restored


def test_each_user_sees_only_their_cart(api, catalog_db):
    pid = _id(catalog_db, "Vector Air 690")
    api.login()
    _add(api, pid, 2)
    api.login()  # another user, new token
    assert api.get("/api/cart").json()["items"] == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/cart"),
        ("post", "/api/cart/items"),
        ("patch", "/api/cart/items/MN-HDP-0004"),
        ("delete", "/api/cart/items/MN-HDP-0004"),
        ("delete", "/api/cart"),
    ],
)
def test_cart_requires_login(api, method, path):
    kwargs = (
        {"json": {"product_id": "MN-HDP-0004", "quantity": 1}}
        if method in ("post", "patch")
        else {}
    )
    response = getattr(api, method)(path, **kwargs)
    assert response.status_code == 401
