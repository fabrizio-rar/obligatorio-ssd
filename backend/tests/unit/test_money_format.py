"""Amounts in the backend-built messages use the same es-UY format as the UI."""

from decimal import Decimal

import pytest

from app.agent.tools import _money


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0", "USD 0,00"),
        ("359.88", "USD 359,88"),
        ("1234.5", "USD 1.234,50"),
        ("2019", "USD 2.019,00"),
        ("1234567.891", "USD 1.234.567,89"),
    ],
)
def test_money_uses_comma_for_decimals(amount, expected):
    assert _money(Decimal(amount)) == expected
