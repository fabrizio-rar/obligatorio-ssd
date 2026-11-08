"""Inventory rules (pure functions, no DB or LLM)."""

from enum import StrEnum

LOW_STOCK_MAX = 2


class StockStatus(StrEnum):
    IN_STOCK = "In stock"
    LOW_STOCK = "Low stock"
    OUT_OF_STOCK = "Out of stock"


def stock_status(available_qty: int) -> StockStatus:
    """Dataset rule: 0 -> Out, 1-2 -> Low, >=3 -> In stock."""
    if available_qty <= 0:
        return StockStatus.OUT_OF_STOCK
    if available_qty <= LOW_STOCK_MAX:
        return StockStatus.LOW_STOCK
    return StockStatus.IN_STOCK
