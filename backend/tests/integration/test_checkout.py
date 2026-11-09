"""Checkout and the purchase transaction (docs/PLAN.md §12.1, §12.2) against the real dataset.

Every test restores inventory, prices and the `active` flag afterwards, so they stay
independent even though the catalog is loaded once per module.
"""

import threading
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import service as auth
from app.domain import cart
from app.domain.checkout import (
    CheckoutRequest,
    ShippingPolicy,
    cancel_order,
    checkout_options,
    confirm_order,
    create_checkout,
    get_order,
    list_orders,
)
from app.domain.errors import DomainError
from app.models import Inventory, Order, Price, Product

pytestmark = pytest.mark.integration

POLICY = ShippingPolicy(cost=Decimal("8.00"), free_from=Decimal("200.00"))
ADDRESS = {"street": "18 de Julio 1234", "city": "Montevideo", "department": "Montevideo"}


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    with catalog_db.bind.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS _inv_snap, _price_snap, _active_snap"))
        conn.execute(text("CREATE TABLE _inv_snap AS SELECT * FROM inventory"))
        conn.execute(text("CREATE TABLE _price_snap AS SELECT * FROM prices"))
        conn.execute(text("CREATE TABLE _active_snap AS SELECT id, active FROM products"))
    yield catalog_db
    with catalog_db.bind.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS _inv_snap, _price_snap, _active_snap"))


@pytest.fixture(autouse=True)
def restore(db):
    yield
    db.rollback()
    with db.bind.begin() as conn:
        conn.execute(
            text(
                "UPDATE inventory i SET on_hand_qty = s.on_hand_qty, reserved_qty = s.reserved_qty "
                "FROM _inv_snap s WHERE s.product_id = i.product_id "
                "AND s.warehouse_id = i.warehouse_id"
            )
        )
        conn.execute(
            text(
                "UPDATE prices p SET current_price = s.current_price, "
                "discount_percent = s.discount_percent FROM _price_snap s "
                "WHERE s.product_id = p.product_id"
            )
        )
        conn.execute(
            text("UPDATE products p SET active = s.active FROM _active_snap s WHERE s.id = p.id")
        )
    db.expire_all()


# --- Helpers ---------------------------------------------------------------------------------


def _id(db, name):
    return db.scalar(select(Product.id).where(Product.name == name))


def _user(db, *items) -> int:
    """A fresh user with these (product_id, quantity) in the cart."""
    user = auth.register(db, f"co{uuid.uuid4().hex[:10]}", "secret123")
    for product_id, quantity in items:
        cart.add_item(db, user.id, product_id, quantity)
    return user.id


def _request(**overrides) -> CheckoutRequest:
    data = {
        "customer_name": "Ana Pérez",
        "email": "ana@example.com",
        "delivery_method": "SHIPPING",
        "shipping_address": ADDRESS,
        "payment_method": "CARD",
    } | overrides
    return CheckoutRequest.model_validate(data)


def _pickup(warehouse_id: str) -> CheckoutRequest:
    return _request(
        delivery_method="PICKUP",
        shipping_address=None,
        pickup_warehouse_id=warehouse_id,
        payment_method="CASH_ON_PICKUP",
    )


def _stock(db, product_id) -> dict[str, int]:
    db.expire_all()
    return dict(
        db.execute(
            select(Inventory.warehouse_id, Inventory.available_qty).where(
                Inventory.product_id == product_id
            )
        ).all()
    )


def _set_stock(db, product_id, per_warehouse: dict[str, int]) -> None:
    for warehouse_id, units in per_warehouse.items():
        db.execute(
            update(Inventory)
            .where(Inventory.product_id == product_id, Inventory.warehouse_id == warehouse_id)
            .values(on_hand_qty=units, reserved_qty=0)
        )
    db.commit()


def _error(fn, *args) -> DomainError:
    with pytest.raises(DomainError) as info:
        fn(*args)
    return info.value


# --- Options and checkout ----------------------------------------------------------------------


def test_options_need_a_cart(db):
    assert _error(checkout_options, db, _user(db), POLICY).code == "EMPTY_CART"


def test_pickup_options_show_the_branches_that_cannot_cover_the_cart(db):
    vector = _id(db, "Vector Air 690")  # Colonia has 0 units in the dataset
    user = _user(db, (vector, 1))
    options = checkout_options(db, user, POLICY)
    colonia = next(o for o in options.pickup if o.warehouse_id == "WH-COL-001")
    assert not colonia.can_fulfill
    assert colonia.missing[0].product_id == vector and colonia.missing[0].available == 0
    # The ones that can come first
    flags = [o.can_fulfill for o in options.pickup]
    assert flags == sorted(flags, reverse=True)
    assert options.payment_methods == ["CARD", "BANK_TRANSFER", "CASH_ON_PICKUP"]


def test_shipping_cost_depends_on_the_subtotal(db):
    cheap = _user(db, (_id(db, "Vector Air 690"), 1))  # USD 74.45
    assert checkout_options(db, cheap, POLICY).shipping.cost == Decimal("8.00")
    order = create_checkout(db, cheap, _request(), POLICY)
    assert order.shipping_cost == Decimal("8.00")
    assert order.total == order.subtotal + Decimal("8.00")

    stock = _stock(db, _id(db, "Vector Air 690"))
    pickup = create_checkout(db, cheap, _pickup(max(stock, key=stock.get)), POLICY)
    assert pickup.shipping_cost == Decimal("0.00") and pickup.total == pickup.subtotal

    expensive = _user(db, (_id(db, "Lumina Sound 757"), 2))  # 2 x 165.07
    assert checkout_options(db, expensive, POLICY).shipping.cost == Decimal("0.00")


def test_checkout_freezes_name_and_price_and_nothing_is_bought(db):
    vector = _id(db, "Vector Air 690")
    user = _user(db, (vector, 2))
    before = _stock(db, vector)
    order = create_checkout(db, user, _request(), POLICY)

    assert order.status == "PENDING_CONFIRMATION"
    assert order.code == f"MN-ORD-{order.order_id:06d}"
    item = order.items[0]
    price = db.scalar(select(Price.current_price).where(Price.product_id == vector))
    assert (item.name, item.unit_price, item.quantity) == ("Vector Air 690", price, 2)
    assert item.line_total == price * 2 and item.allocations == []
    assert _stock(db, vector) == before  # no reservation (PLAN §18, decision 15)
    assert cart.get_cart(db, user).item_count == 2  # the cart stays until the purchase


def test_pickup_at_a_branch_without_stock_is_rejected_with_the_alternatives(db):
    user = _user(db, (_id(db, "Vector Air 690"), 1))
    error = _error(create_checkout, db, user, _pickup("WH-COL-001"), POLICY)
    assert error.code == "PICKUP_UNAVAILABLE"
    assert error.details["suggestion"] == "SHIPPING"
    assert "WH-COL-001" not in error.details["warehouses_that_can"]
    assert error.details["warehouses_that_can"]


@pytest.mark.parametrize("warehouse_id", ["WH-XXX-000", ""])
def test_unknown_pickup_branch(db, warehouse_id):
    user = _user(db, (_id(db, "Vector Air 690"), 1))
    request = _pickup("WH-COL-001").model_copy(update={"pickup_warehouse_id": warehouse_id})
    assert _error(create_checkout, db, user, request, POLICY).code == "INVALID_INPUT"


def test_cart_with_issues_cannot_go_to_checkout(db):
    vector = _id(db, "Vector Air 690")
    user = _user(db, (vector, 1))
    db.execute(update(Product).where(Product.id == vector).values(active=False))
    db.commit()
    error = _error(create_checkout, db, user, _request(), POLICY)
    assert error.code == "CART_HAS_ISSUES"
    assert error.details["items"][0]["issues"] == ["INACTIVE"]


def test_a_new_checkout_replaces_the_pending_one(db):
    user = _user(db, (_id(db, "Vector Air 690"), 1))
    first = create_checkout(db, user, _request(), POLICY)
    stock = _stock(db, _id(db, "Vector Air 690"))
    second = create_checkout(db, user, _pickup(max(stock, key=stock.get)), POLICY)
    assert get_order(db, user, first.code).status == "CANCELLED"
    assert get_order(db, user, second.code).status == "PENDING_CONFIRMATION"


# --- The purchase ------------------------------------------------------------------------------


def test_confirm_shipping_discounts_stock_greedily_and_empties_the_cart(db):
    vector = _id(db, "Vector Air 690")
    _set_stock(
        db,
        vector,
        dict.fromkeys(_stock(db, vector), 0) | {"WH-MVD-CEN": 2, "WH-MVD-EST": 3, "WH-CAN-001": 1},
    )
    before = _stock(db, vector)
    user = _user(db, (vector, 4))
    order = create_checkout(db, user, _request(), POLICY)

    confirmed = confirm_order(db, user, order.order_id, POLICY)

    assert confirmed.status == "CONFIRMED" and confirmed.confirmed_at is not None
    allocation = {a.warehouse_id: a.quantity for a in confirmed.items[0].allocations}
    assert allocation == {"WH-MVD-EST": 3, "WH-MVD-CEN": 1}  # the biggest first, then the next
    after = _stock(db, vector)
    assert {w: before[w] - after[w] for w in before if before[w] != after[w]} == allocation
    assert cart.get_cart(db, user).items == []
    assert [o.code for o in list_orders(db, user).items] == [order.code]


def test_confirm_pickup_takes_everything_from_the_chosen_branch(db):
    vector = _id(db, "Vector Air 690")
    before = _stock(db, vector)
    branch = max(before, key=before.get)
    user = _user(db, (vector, 2))
    order = create_checkout(db, user, _pickup(branch), POLICY)
    confirmed = confirm_order(db, user, order.order_id, POLICY)

    assert [(a.warehouse_id, a.quantity) for a in confirmed.items[0].allocations] == [(branch, 2)]
    after = _stock(db, vector)
    assert after[branch] == before[branch] - 2
    assert all(after[w] == before[w] for w in before if w != branch)


def test_double_confirm_is_idempotent(db):
    vector = _id(db, "Vector Air 690")
    before = sum(_stock(db, vector).values())
    user = _user(db, (vector, 1))
    order = create_checkout(db, user, _request(), POLICY)
    first = confirm_order(db, user, order.order_id, POLICY)
    second = confirm_order(db, user, order.order_id, POLICY)

    assert first.code == second.code and second.status == "CONFIRMED"
    assert sum(_stock(db, vector).values()) == before - 1  # bought once
    assert sum(a.quantity for a in second.items[0].allocations) == 1


def test_price_change_updates_the_order_and_asks_to_confirm_again(db):
    vector = _id(db, "Vector Air 690")
    before = _stock(db, vector)
    user = _user(db, (vector, 1))
    order = create_checkout(db, user, _request(), POLICY)
    db.execute(
        update(Price).where(Price.product_id == vector).values(current_price=Decimal("69.90"))
    )
    db.commit()

    error = _error(confirm_order, db, user, order.order_id, POLICY)

    assert error.code == "PRICE_CHANGED"
    assert error.details["changes"][0]["new_price"] == "69.90"
    assert "USD 69,90" in error.message
    assert error.details["order"]["total"] == "77.90"  # 69.90 + shipping 8
    assert _stock(db, vector) == before  # nothing bought
    pending = get_order(db, user, order.code)
    assert pending.status == "PENDING_CONFIRMATION" and pending.items[0].unit_price == Decimal(
        "69.90"
    )

    confirmed = confirm_order(db, user, order.order_id, POLICY)  # the user confirms again
    assert confirmed.status == "CONFIRMED" and confirmed.total == Decimal("77.90")


def test_product_discontinued_before_confirming(db):
    vector = _id(db, "Vector Air 690")
    user = _user(db, (vector, 1))
    order = create_checkout(db, user, _request(), POLICY)
    db.execute(update(Product).where(Product.id == vector).values(active=False))
    db.commit()
    assert _error(confirm_order, db, user, order.order_id, POLICY).code == "INACTIVE"
    assert get_order(db, user, order.code).status == "PENDING_CONFIRMATION"


def test_stock_gone_before_confirming_rolls_everything_back(db):
    vector, lumina = _id(db, "Vector Air 690"), _id(db, "Lumina Sound 757")
    user = _user(db, (lumina, 1), (vector, 2))
    order = create_checkout(db, user, _request(), POLICY)
    lumina_before = _stock(db, lumina)
    _set_stock(db, vector, dict.fromkeys(_stock(db, vector), 0) | {"WH-MVD-CEN": 1})

    error = _error(confirm_order, db, user, order.order_id, POLICY)

    assert error.code == "OUT_OF_STOCK"
    assert error.details["items"] == [
        {"product_id": vector, "name": "Vector Air 690", "requested": 2, "available": 1}
    ]
    assert _stock(db, lumina) == lumina_before  # the other item was not discounted either
    assert get_order(db, user, order.code).status == "PENDING_CONFIRMATION"
    assert cart.get_cart(db, user).item_count == 3


def test_pickup_branch_emptied_before_confirming(db):
    vector = _id(db, "Vector Air 690")
    _set_stock(db, vector, {"WH-MVD-CEN": 3, "WH-MVD-EST": 5})
    user = _user(db, (vector, 1))
    order = create_checkout(db, user, _pickup("WH-MVD-CEN"), POLICY)
    _set_stock(db, vector, {"WH-MVD-CEN": 0})  # the other branches still have stock
    error = _error(confirm_order, db, user, order.order_id, POLICY)
    assert error.code == "OUT_OF_STOCK" and error.details["warehouse_id"] == "WH-MVD-CEN"


def test_cart_changed_after_the_summary(db):
    vector, lumina = _id(db, "Vector Air 690"), _id(db, "Lumina Sound 757")
    user = _user(db, (vector, 1))
    order = create_checkout(db, user, _request(), POLICY)
    cart.add_item(db, user, lumina, 1)
    assert _error(confirm_order, db, user, order.order_id, POLICY).code == "CART_CHANGED"


def test_cancel_rules(db):
    user = _user(db, (_id(db, "Vector Air 690"), 1))
    order = create_checkout(db, user, _request(), POLICY)
    assert cancel_order(db, user, order.order_id).status == "CANCELLED"
    assert cancel_order(db, user, order.order_id).status == "CANCELLED"  # idempotent
    assert _error(confirm_order, db, user, order.order_id, POLICY).code == "ORDER_CANCELLED"

    again = create_checkout(db, user, _request(), POLICY)
    confirm_order(db, user, again.order_id, POLICY)
    assert _error(cancel_order, db, user, again.order_id).code == "ORDER_NOT_CANCELLABLE"


def test_orders_belong_to_their_user(db):
    owner = _user(db, (_id(db, "Vector Air 690"), 1))
    order = create_checkout(db, owner, _request(), POLICY)
    other = _user(db)
    assert _error(confirm_order, db, other, order.order_id, POLICY).code == "ORDER_NOT_FOUND"
    assert _error(get_order, db, other, order.code).code == "ORDER_NOT_FOUND"
    assert _error(cancel_order, db, other, order.order_id).code == "ORDER_NOT_FOUND"


def test_history_lists_only_purchases_newest_first(db):
    vector = _id(db, "Vector Air 690")
    user = _user(db, (vector, 1))
    first = create_checkout(db, user, _request(), POLICY)
    confirm_order(db, user, first.order_id, POLICY)
    cart.add_item(db, user, vector, 1)
    second = create_checkout(db, user, _request(), POLICY)
    confirm_order(db, user, second.order_id, POLICY)
    cart.add_item(db, user, vector, 1)
    create_checkout(db, user, _request(), POLICY)  # pending: not a purchase

    history = list_orders(db, user)
    assert history.total == 2
    assert [o.code for o in history.items] == [second.code, first.code]
    assert history.items[0].product_names == ["Vector Air 690"]


def test_db_constraints_back_the_rules(db):
    user = _user(db)
    bad = Order(
        user_id=user,
        status="PENDING_CONFIRMATION",
        customer_name="x",
        email="x@x.x",
        delivery_method="SHIPPING",
        shipping_address=None,  # shipping without an address
        payment_method="CARD",
        currency="USD",
        subtotal=1,
        shipping_cost=0,
        total=1,
    )
    db.add(bad)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- Concurrency: two purchases of the last unit -------------------------------------------------


def test_two_buyers_for_the_last_unit_only_one_wins(db):
    vector = _id(db, "Vector Air 690")
    _set_stock(db, vector, dict.fromkeys(_stock(db, vector), 0) | {"WH-MVD-CEN": 1})
    buyers = [_user(db, (vector, 1)) for _ in range(2)]
    orders = [create_checkout(db, u, _request(), POLICY).order_id for u in buyers]
    db.commit()

    results: list[str] = []
    barrier = threading.Barrier(2)

    def buy(user_id: int, order_id: int) -> None:
        with Session(db.bind) as session:  # its own connection, like two real requests
            barrier.wait()
            try:
                results.append(confirm_order(session, user_id, order_id, POLICY).status)
            except DomainError as error:
                results.append(error.code)

    threads = [threading.Thread(target=buy, args=pair) for pair in zip(buyers, orders, strict=True)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(results) == ["CONFIRMED", "OUT_OF_STOCK"]
    stock = _stock(db, vector)
    assert stock["WH-MVD-CEN"] == 0 and min(stock.values()) >= 0


# --- API ---------------------------------------------------------------------------------------


def test_api_full_purchase(api, db):
    api.login()
    vector = _id(db, "Vector Air 690")
    assert (
        api.post("/api/cart/items", json={"product_id": vector, "quantity": 1}).status_code == 200
    )
    options = api.get("/api/checkout/options").json()
    assert options["shipping"]["cost"] == "8.00" and options["pickup"]

    body = _request().model_dump(mode="json")
    created = api.post("/api/checkout", json=body)
    assert created.status_code == 201
    order = created.json()
    confirmed = api.post(f"/api/orders/{order['order_id']}/confirm").json()
    assert confirmed["status"] == "CONFIRMED" and confirmed["items"][0]["allocations"]
    assert api.get(f"/api/orders/{order['code']}").json()["status"] == "CONFIRMED"
    assert api.get("/api/orders").json()["total"] == 1
    assert api.get("/api/cart").json()["items"] == []


def test_api_errors_use_the_uniform_format(api, db):
    api.login()
    empty = api.post("/api/checkout", json=_request().model_dump(mode="json"))
    assert empty.status_code == 409 and empty.json()["error"]["code"] == "EMPTY_CART"

    invalid = api.post("/api/checkout", json={"customer_name": "A", "email": "nope"})
    assert invalid.status_code == 422
    error = invalid.json()["error"]
    assert error["code"] == "INVALID_INPUT"
    fields = {f["field"]: f["message"] for f in error["details"]["fields"]}
    assert fields["customer_name"] == "Tiene que tener al menos 2 caracteres"
    assert fields["email"] == "El email no es válido"
    assert fields["delivery_method"] == "Falta este dato"

    assert api.post("/api/orders/999999/confirm").status_code == 404
    assert api.get("/api/orders/MN-ORD-999999").status_code == 404


def test_api_requires_login(api):
    api.headers.pop("Authorization", None)
    for method, path in [
        ("get", "/api/checkout/options"),
        ("post", "/api/checkout"),
        ("post", "/api/orders/1/confirm"),
        ("get", "/api/orders"),
    ]:
        assert getattr(api, method)(path).status_code == 401
