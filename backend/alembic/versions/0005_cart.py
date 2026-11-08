"""Cart: carts (one per user) and cart_items (no price: always the current one).

Revision ID: 0005_cart
Revises: 0004_auth
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_cart"
down_revision: str | None = "0004_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "carts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "cart_items",
        sa.Column(
            "cart_id",
            sa.Integer,
            sa.ForeignKey("carts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("added_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_cart_items_quantity"),
    )


def downgrade() -> None:
    op.drop_table("cart_items")
    op.drop_table("carts")
