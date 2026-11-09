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


# --- Allocation per warehouse (docs/PLAN.md §12.2) --------------------------------------------
# `stock` maps warehouse_id -> available units of ONE product, only the warehouses that count
# (shipping-enabled ones for SHIPPING, the chosen one for PICKUP). The result maps
# warehouse_id -> units taken, or None if the stock is not enough. Pure: no DB.

Allocation = dict[str, int]


def allocate_shipping(stock: dict[str, int], quantity: int) -> Allocation | None:
    """Greedy: the warehouse with the most units first; if it is not enough, the next one.
    Ties go by warehouse id, so the result is deterministic."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if sum(max(units, 0) for units in stock.values()) < quantity:
        return None
    allocation: Allocation = {}
    missing = quantity
    for warehouse_id, units in sorted(stock.items(), key=lambda kv: (-kv[1], kv[0])):
        if missing == 0:
            break
        take = min(units, missing)
        if take > 0:
            allocation[warehouse_id] = take
            missing -= take
    return allocation


def allocate_pickup(stock: dict[str, int], warehouse_id: str, quantity: int) -> Allocation | None:
    """Everything from the chosen warehouse, or nothing."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if stock.get(warehouse_id, 0) < quantity:
        return None
    return {warehouse_id: quantity}
