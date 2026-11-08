"""Cart rules (pure business logic: no LLM, no HTTP). The REST API and, later, the agent's
cart tools call these SAME functions (AGENTS.md rule 1). `user_id` always comes from the
session token.

Stock is validated in two moments (RF-10):
    - here, "soft": against the TOTAL available stock, nothing is reserved;
    - at checkout confirmation (N6), "hard": inside the purchase transaction, per warehouse.
"""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.domain.inventory import StockStatus, stock_status
from app.models import Brand, Cart, CartItem, Category, Price, Product, Subcategory
from app.models.catalog import product_availability

MAX_QUANTITY_PER_ITEM = 10

Issue = Literal["INACTIVE", "OUT_OF_STOCK", "INSUFFICIENT_STOCK"]


class CartItemView(BaseModel):
    product_id: str
    sku: str
    name: str
    brand: str
    category: str
    image_url: str | None
    currency: str
    unit_price: Decimal  # CURRENT price (not stored in the cart)
    list_price: Decimal
    discount_percent: int
    quantity: int
    line_total: Decimal  # 0 for an inactive product: it cannot be bought
    available: int
    stock_status: StockStatus
    active: bool
    # A product that stopped being sellable is NOT silently removed: it is flagged here
    issues: list[Issue]


class CartView(BaseModel):
    items: list[CartItemView]
    item_count: int  # sum of quantities (the badge)
    currency: str = "USD"
    total: Decimal  # prices include taxes; no shipping cost in this prototype
    can_checkout: bool  # at least one item and no issues


# --- Helpers ----------------------------------------------------------------------------------


def _cart_id(session: Session, user_id: int, create: bool) -> int | None:
    cart_id = session.scalar(select(Cart.id).where(Cart.user_id == user_id))
    if cart_id is None and create:
        # ON CONFLICT: two first requests at the same time create only one cart
        session.execute(insert(Cart).values(user_id=user_id).on_conflict_do_nothing())
        cart_id = session.scalar(select(Cart.id).where(Cart.user_id == user_id))
    return cart_id


def _touch(session: Session, cart_id: int) -> None:
    session.execute(update(Cart).where(Cart.id == cart_id).values(updated_at=func.now()))


def _sellable(session: Session, product_id: str) -> int:
    """Total available stock of a product that can be sold. Raises NOT_FOUND / INACTIVE."""
    product = session.get(Product, product_id)
    if product is None:
        raise DomainError(
            "NOT_FOUND", f"Product {product_id} does not exist", {"product_id": product_id}
        )
    if not product.active:
        raise DomainError(
            "INACTIVE",
            f"{product.name} está discontinuado y no se puede comprar",
            {"product_id": product_id},
        )
    return (
        session.scalar(
            select(product_availability.c.available).where(
                product_availability.c.product_id == product_id
            )
        )
        or 0
    )


def _check_quantity(quantity: int) -> None:
    if not 1 <= quantity <= MAX_QUANTITY_PER_ITEM:
        raise DomainError(
            "INVALID_INPUT",
            f"La cantidad tiene que estar entre 1 y {MAX_QUANTITY_PER_ITEM}",
            {"field": "quantity", "max": MAX_QUANTITY_PER_ITEM},
        )


def _check_stock(session: Session, product_id: str, wanted: int, in_cart: int) -> None:
    available = _sellable(session, product_id)
    if wanted > available:
        name = session.get(Product, product_id).name
        message = (
            f"{name} no tiene stock"
            if available == 0
            else f"Solo hay {available} unidades de {name}"
        )
        raise DomainError(
            "OUT_OF_STOCK",
            message,
            {"product_id": product_id, "available": available, "in_cart": in_cart},
        )


def _quantity_in_cart(session: Session, cart_id: int | None, product_id: str) -> int | None:
    if cart_id is None:
        return None
    return session.scalar(
        select(CartItem.quantity).where(
            CartItem.cart_id == cart_id, CartItem.product_id == product_id
        )
    )


# --- Queries and mutations --------------------------------------------------------------------


def get_cart(session: Session, user_id: int) -> CartView:
    cart_id = _cart_id(session, user_id, create=False)
    if cart_id is None:
        return CartView(items=[], item_count=0, total=Decimal("0.00"), can_checkout=False)

    rows = session.execute(
        select(
            CartItem, Product, Brand.name, Category.name, Price, product_availability.c.available
        )
        .join(Product, Product.id == CartItem.product_id)
        .join(Brand, Brand.id == Product.brand_id)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .join(Price, Price.product_id == Product.id)
        .join(product_availability, product_availability.c.product_id == Product.id)
        .where(CartItem.cart_id == cart_id)
        .order_by(CartItem.added_at, CartItem.product_id)
    ).all()

    items = []
    for item, product, brand, category, price, available in rows:
        issues: list[Issue] = []
        if not product.active:
            issues.append("INACTIVE")
        elif available == 0:
            issues.append("OUT_OF_STOCK")
        elif item.quantity > available:
            issues.append("INSUFFICIENT_STOCK")
        items.append(
            CartItemView(
                product_id=product.id,
                sku=product.sku,
                name=product.name,
                brand=brand,
                category=category,
                image_url=product.image_url,
                currency=price.currency,
                unit_price=price.current_price,
                list_price=price.list_price,
                discount_percent=price.discount_percent,
                quantity=item.quantity,
                line_total=price.current_price * item.quantity
                if product.active
                else Decimal("0.00"),
                available=available,
                stock_status=stock_status(available),
                active=product.active,
                issues=issues,
            )
        )
    return CartView(
        items=items,
        item_count=sum(i.quantity for i in items),
        total=sum((i.line_total for i in items), Decimal("0.00")),
        can_checkout=bool(items) and not any(i.issues for i in items),
    )


def add_item(session: Session, user_id: int, product_id: str, quantity: int = 1) -> CartView:
    """Adds `quantity` units (sums if the product is already in the cart)."""
    _check_quantity(quantity)
    cart_id = _cart_id(session, user_id, create=False)
    current = _quantity_in_cart(session, cart_id, product_id) or 0
    if current + quantity > MAX_QUANTITY_PER_ITEM:
        raise DomainError(
            "INVALID_INPUT",
            f"Podés tener hasta {MAX_QUANTITY_PER_ITEM} unidades de un mismo producto",
            {"field": "quantity", "max": MAX_QUANTITY_PER_ITEM, "in_cart": current},
        )
    _check_stock(session, product_id, current + quantity, current)

    cart_id = _cart_id(session, user_id, create=True)
    stmt = insert(CartItem).values(cart_id=cart_id, product_id=product_id, quantity=quantity)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["cart_id", "product_id"],
            set_={"quantity": CartItem.quantity + stmt.excluded.quantity},
        )
    )
    _touch(session, cart_id)
    session.commit()
    return get_cart(session, user_id)


def set_quantity(session: Session, user_id: int, product_id: str, quantity: int) -> CartView:
    _check_quantity(quantity)
    cart_id = _cart_id(session, user_id, create=False)
    current = _quantity_in_cart(session, cart_id, product_id)
    if current is None:
        raise DomainError(
            "NOT_IN_CART", "Ese producto no está en el carrito", {"product_id": product_id}
        )
    _check_stock(session, product_id, quantity, current)
    session.execute(
        update(CartItem)
        .where(CartItem.cart_id == cart_id, CartItem.product_id == product_id)
        .values(quantity=quantity)
    )
    _touch(session, cart_id)
    session.commit()
    return get_cart(session, user_id)


def remove_item(session: Session, user_id: int, product_id: str) -> CartView:
    cart_id = _cart_id(session, user_id, create=False)
    if _quantity_in_cart(session, cart_id, product_id) is None:
        raise DomainError(
            "NOT_IN_CART", "Ese producto no está en el carrito", {"product_id": product_id}
        )
    session.execute(
        delete(CartItem).where(CartItem.cart_id == cart_id, CartItem.product_id == product_id)
    )
    _touch(session, cart_id)
    session.commit()
    return get_cart(session, user_id)


def clear_cart(session: Session, user_id: int) -> CartView:
    cart_id = _cart_id(session, user_id, create=False)
    if cart_id is not None:
        session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
        _touch(session, cart_id)
        session.commit()
    return get_cart(session, user_id)
