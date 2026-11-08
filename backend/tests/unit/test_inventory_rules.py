import pytest

from app.domain.inventory import StockStatus, stock_status


@pytest.mark.parametrize(
    ("qty", "expected"),
    [
        (0, StockStatus.OUT_OF_STOCK),
        (-1, StockStatus.OUT_OF_STOCK),
        (1, StockStatus.LOW_STOCK),
        (2, StockStatus.LOW_STOCK),
        (3, StockStatus.IN_STOCK),
        (50, StockStatus.IN_STOCK),
    ],
)
def test_stock_status_rule(qty, expected):
    assert stock_status(qty) is expected
