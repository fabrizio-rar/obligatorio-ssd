"""Pure checkout rules: allocation per warehouse, shipping cost and the checkout form."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.checkout import (
    CheckoutRequest,
    DeliveryMethod,
    PaymentMethod,
    ShippingPolicy,
    shipping_cost,
)
from app.domain.inventory import allocate_pickup, allocate_shipping

# --- Shipping: greedy, the warehouse with the most units first --------------------------------


def test_one_warehouse_is_enough_and_it_is_the_biggest():
    assert allocate_shipping({"A": 3, "B": 9, "C": 5}, 4) == {"B": 4}


def test_split_across_warehouses_when_one_is_not_enough():
    assert allocate_shipping({"A": 3, "B": 4, "C": 2}, 8) == {"B": 4, "A": 3, "C": 1}


def test_ties_go_by_warehouse_id_so_the_result_is_deterministic():
    assert allocate_shipping({"B": 5, "A": 5}, 7) == {"A": 5, "B": 2}


def test_exact_total_and_empty_warehouses_are_skipped():
    assert allocate_shipping({"A": 0, "B": 2, "C": 1}, 3) == {"B": 2, "C": 1}


def test_not_enough_stock_in_total():
    assert allocate_shipping({"A": 1, "B": 1}, 3) is None
    assert allocate_shipping({}, 1) is None


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantity_must_be_positive(quantity):
    with pytest.raises(ValueError):
        allocate_shipping({"A": 5}, quantity)
    with pytest.raises(ValueError):
        allocate_pickup({"A": 5}, "A", quantity)


# --- Pickup: only the chosen warehouse --------------------------------------------------------


def test_pickup_takes_everything_from_the_chosen_warehouse():
    assert allocate_pickup({"A": 9, "B": 2}, "B", 2) == {"B": 2}


def test_pickup_never_takes_from_another_warehouse():
    assert allocate_pickup({"A": 9, "B": 1}, "B", 2) is None
    assert allocate_pickup({"A": 9}, "Z", 1) is None


# --- Shipping cost ------------------------------------------------------------------------------

POLICY = ShippingPolicy(cost=Decimal("8"), free_from=Decimal("200"))


@pytest.mark.parametrize(
    ("method", "subtotal", "expected"),
    [
        (DeliveryMethod.SHIPPING, "199.99", "8.00"),
        (DeliveryMethod.SHIPPING, "200.00", "0.00"),  # free FROM 200, inclusive
        (DeliveryMethod.SHIPPING, "1500", "0.00"),
        (DeliveryMethod.PICKUP, "10", "0.00"),  # pickup is always free
    ],
)
def test_shipping_cost(method, subtotal, expected):
    assert shipping_cost(method, Decimal(subtotal), POLICY) == Decimal(expected)


# --- Checkout form ------------------------------------------------------------------------------

ADDRESS = {"street": "18 de Julio 1234", "city": "Montevideo", "department": "Montevideo"}


def _request(**overrides):
    data = {
        "customer_name": "  Ana Pérez ",
        "email": "Ana@Example.com",
        "delivery_method": "SHIPPING",
        "shipping_address": ADDRESS,
        "pickup_warehouse_id": None,
        "payment_method": "CARD",
    } | overrides
    return CheckoutRequest.model_validate(data)


def test_valid_shipping_request_is_normalized():
    request = _request()
    assert request.customer_name == "Ana Pérez"
    assert request.email == "ana@example.com"


def test_pickup_drops_a_stray_address_and_shipping_a_stray_warehouse():
    pickup = _request(delivery_method="PICKUP", pickup_warehouse_id="WH-COL-001")
    assert pickup.shipping_address is None
    shipping = _request(pickup_warehouse_id="WH-COL-001")
    assert shipping.pickup_warehouse_id is None


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"shipping_address": None}, "dirección"),
        ({"delivery_method": "PICKUP", "shipping_address": None}, "sucursal"),
        ({"payment_method": "CASH_ON_PICKUP"}, "efectivo"),
        ({"email": "ana@"}, "email"),
        ({"customer_name": "A"}, "at least 2"),
        ({"payment_method": "CRYPTO"}, "CARD"),
        ({"shipping_address": {**ADDRESS, "street": "x"}}, "at least 3"),
    ],
)
def test_invalid_requests(overrides, message):
    with pytest.raises(ValidationError) as info:
        _request(**overrides)
    assert message in str(info.value)


def test_cash_is_allowed_with_pickup():
    request = _request(
        delivery_method="PICKUP", pickup_warehouse_id="WH-COL-001", payment_method="CASH_ON_PICKUP"
    )
    assert request.payment_method == PaymentMethod.CASH_ON_PICKUP
