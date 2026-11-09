"""Orders (docs/PLAN.md §7.2, §12.1): the checkout creates an order PENDING_CONFIRMATION with
the quoted prices; only POST /api/orders/{id}/confirm (a UI button, never the agent) turns it
into CONFIRMED, inside one transaction that discounts stock per warehouse."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # MN-ORD-000123, computed by Postgres from the id
    code: Mapped[str] = mapped_column(
        String(16), Computed("'MN-ORD-' || lpad(id::text, 6, '0')", persisted=True), unique=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(24))  # PENDING_CONFIRMATION | CONFIRMED | CANCELLED
    customer_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    delivery_method: Mapped[str] = mapped_column(String(16))  # SHIPPING | PICKUP
    # none_as_null: Python None must be SQL NULL (not JSON 'null'), so the CHECK below sees it
    shipping_address: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    pickup_warehouse_id: Mapped[str | None] = mapped_column(ForeignKey("warehouses.id"))
    payment_method: Mapped[str] = mapped_column(String(24))  # CARD | BANK_TRANSFER | CASH_ON_PICKUP
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    shipping_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    confirmed_at: Mapped[datetime | None]
    cancelled_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'CANCELLED')", name="ck_orders_status"
        ),
        CheckConstraint(
            "(delivery_method = 'SHIPPING' AND shipping_address IS NOT NULL) OR "
            "(delivery_method = 'PICKUP' AND pickup_warehouse_id IS NOT NULL)",
            name="ck_orders_delivery",
        ),
        CheckConstraint(
            "payment_method IN ('CARD', 'BANK_TRANSFER', 'CASH_ON_PICKUP') AND "
            "(payment_method <> 'CASH_ON_PICKUP' OR delivery_method = 'PICKUP')",
            name="ck_orders_payment",
        ),
    )


class OrderItem(Base):
    """Name, SKU and price are FROZEN at checkout time (they are what the user saw)."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"))
    product_name: Mapped[str] = mapped_column(Text)
    sku: Mapped[str] = mapped_column(Text)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    quantity: Mapped[int]
    line_total: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    __table_args__ = (
        UniqueConstraint("order_id", "product_id", name="uq_order_items_product"),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
    )


class OrderItemAllocation(Base):
    """Which warehouse each unit came from (RF-15 evidence). Pickup: always the chosen one."""

    __tablename__ = "order_item_allocations"

    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("order_items.id", ondelete="CASCADE"), primary_key=True
    )
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    quantity: Mapped[int]

    __table_args__ = (CheckConstraint("quantity > 0", name="ck_allocations_quantity"),)
