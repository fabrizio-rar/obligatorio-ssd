"""Orders: orders, order_items (frozen name and price) and order_item_allocations.

Revision ID: 0006_orders
Revises: 0005_cart
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0006_orders"
down_revision: str | None = "0005_cart"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "code",
            sa.String(16),
            sa.Computed("'MN-ORD-' || lpad(id::text, 6, '0')", persisted=True),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("customer_name", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("delivery_method", sa.String(16), nullable=False),
        sa.Column("shipping_address", JSONB),
        sa.Column("pickup_warehouse_id", sa.String(16), sa.ForeignKey("warehouses.id")),
        sa.Column("payment_method", sa.String(24), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("shipping_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime),
        sa.Column("cancelled_at", sa.DateTime),
        sa.CheckConstraint(
            "status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'CANCELLED')", name="ck_orders_status"
        ),
        sa.CheckConstraint(
            "(delivery_method = 'SHIPPING' AND shipping_address IS NOT NULL) OR "
            "(delivery_method = 'PICKUP' AND pickup_warehouse_id IS NOT NULL)",
            name="ck_orders_delivery",
        ),
        sa.CheckConstraint(
            "payment_method IN ('CARD', 'BANK_TRANSFER', 'CASH_ON_PICKUP') AND "
            "(payment_method <> 'CASH_ON_PICKUP' OR delivery_method = 'PICKUP')",
            name="ck_orders_payment",
        ),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "order_id", sa.Integer, sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("product_name", sa.Text, nullable=False),
        sa.Column("sku", sa.Text, nullable=False),
        sa.Column("unit_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("line_total", sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint("order_id", "product_id", name="uq_order_items_product"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table(
        "order_item_allocations",
        sa.Column(
            "order_item_id",
            sa.Integer,
            sa.ForeignKey("order_items.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("warehouse_id", sa.String(16), sa.ForeignKey("warehouses.id"), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_allocations_quantity"),
    )


def downgrade() -> None:
    op.drop_table("order_item_allocations")
    op.drop_table("order_items")
    op.drop_index("ix_orders_user_id", table_name="orders")
    op.drop_table("orders")
