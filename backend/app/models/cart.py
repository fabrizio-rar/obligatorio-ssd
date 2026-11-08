"""Shopping cart (docs/PLAN.md §7.2): one active cart per user. No price is stored:
the current one is always read from `prices` (it is frozen later, in the order)."""

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Cart(Base):
    __tablename__ = "carts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CartItem(Base):
    __tablename__ = "cart_items"

    cart_id: Mapped[int] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[str] = mapped_column(String(32), ForeignKey("products.id"), primary_key=True)
    quantity: Mapped[int]
    added_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (CheckConstraint("quantity > 0", name="ck_cart_items_quantity"),)
