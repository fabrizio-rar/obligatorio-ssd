"""Checkout and orders (docs/PLAN.md §12.1, §12.2). Pure business logic: no LLM, no HTTP.
The REST API and, later, the agent's order tools call these SAME functions. `user_id` always
comes from the session token.

Flow (a deterministic workflow: the LLM is never part of it):
    1. checkout_options(): what the form needs (pickup branches that cover the cart, shipping
       cost, payment methods).
    2. create_checkout(): validates the cart and the delivery method and creates an order
       PENDING_CONFIRMATION with the QUOTED prices. Nothing is reserved (PLAN §18, decision 15).
    3. confirm_order(): the purchase. ONE transaction that locks the rows it reads, revalidates
       cart, active product, price and stock, discounts on_hand per warehouse, confirms and
       empties the cart. All or nothing.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.domain.cart import CartView, get_cart
from app.domain.errors import DomainError
from app.domain.inventory import Allocation, allocate_pickup, allocate_shipping
from app.domain.money import format_usd
from app.models import (
    Cart,
    CartItem,
    Category,
    Inventory,
    Order,
    OrderItem,
    OrderItemAllocation,
    Price,
    Product,
    Subcategory,
    Warehouse,
)

CENT = Decimal("0.01")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_ORDERS_PAGE = 50


class DeliveryMethod(StrEnum):
    SHIPPING = "SHIPPING"
    PICKUP = "PICKUP"


class PaymentMethod(StrEnum):
    """Simulated: no card data is ever asked for or stored."""

    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    CASH_ON_PICKUP = "CASH_ON_PICKUP"  # only with PICKUP


class OrderStatus(StrEnum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class ShippingPolicy:
    """From the settings (SHIPPING_COST_USD, FREE_SHIPPING_FROM_USD)."""

    cost: Decimal
    free_from: Decimal


def shipping_cost(method: DeliveryMethod, subtotal: Decimal, policy: ShippingPolicy) -> Decimal:
    """Pickup is free; shipping is free from `free_from`, otherwise the fixed cost."""
    if method == DeliveryMethod.PICKUP or subtotal >= policy.free_from:
        return Decimal("0.00")
    return policy.cost.quantize(CENT)


# --- Input -----------------------------------------------------------------------------------


class ShippingAddress(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    street: str = Field(min_length=3, max_length=200, description="Calle y número")
    city: str = Field(min_length=2, max_length=80)
    department: str = Field(min_length=2, max_length=80)


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    customer_name: str = Field(min_length=2, max_length=100)
    email: str = Field(max_length=254)
    delivery_method: DeliveryMethod
    shipping_address: ShippingAddress | None = None
    pickup_warehouse_id: str | None = None
    payment_method: PaymentMethod

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        if not EMAIL_RE.match(value):
            raise ValueError("El email no es válido")
        return value.lower()

    @model_validator(mode="after")
    def consistent_delivery(self) -> Self:
        if self.delivery_method == DeliveryMethod.SHIPPING:
            if self.shipping_address is None:
                raise ValueError("El envío a domicilio necesita una dirección")
            if self.payment_method == PaymentMethod.CASH_ON_PICKUP:
                raise ValueError("El pago en efectivo es solo para retiro en sucursal")
            self.pickup_warehouse_id = None
        else:
            if not self.pickup_warehouse_id:
                raise ValueError("El retiro en sucursal necesita una sucursal")
            self.shipping_address = None
        return self


# --- Output ----------------------------------------------------------------------------------


class WarehouseRef(BaseModel):
    warehouse_id: str
    name: str
    city: str | None
    department: str | None


class AllocationView(BaseModel):
    warehouse_id: str
    warehouse_name: str
    quantity: int


class OrderItemView(BaseModel):
    product_id: str
    name: str  # frozen at checkout
    sku: str
    category: str | None
    image_url: str | None
    unit_price: Decimal  # frozen at checkout (revalidated at confirmation)
    quantity: int
    line_total: Decimal
    allocations: list[AllocationView]  # empty until confirmed


class OrderView(BaseModel):
    order_id: int
    code: str
    status: OrderStatus
    created_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    customer_name: str
    email: str
    delivery_method: DeliveryMethod
    shipping_address: ShippingAddress | None
    pickup_warehouse: WarehouseRef | None
    payment_method: PaymentMethod
    currency: str
    items: list[OrderItemView]
    item_count: int
    subtotal: Decimal
    shipping_cost: Decimal
    total: Decimal


class OrderSummary(BaseModel):
    order_id: int
    code: str
    status: OrderStatus
    created_at: datetime
    confirmed_at: datetime | None
    delivery_method: DeliveryMethod
    item_count: int
    product_names: list[str]  # first 3, for the list
    currency: str
    total: Decimal


class OrderList(BaseModel):
    items: list[OrderSummary]
    total: int


class MissingItem(BaseModel):
    product_id: str
    name: str
    requested: int
    available: int


class PickupOption(WarehouseRef):
    can_fulfill: bool  # has stock of the WHOLE cart
    missing: list[MissingItem]


class ShippingQuote(BaseModel):
    cost: Decimal  # for this cart
    base_cost: Decimal
    free_from: Decimal


class CheckoutOptions(BaseModel):
    currency: str
    subtotal: Decimal
    item_count: int
    shipping: ShippingQuote
    pickup: list[PickupOption]  # the ones that cover the whole cart first
    payment_methods: list[PaymentMethod]


# --- Helpers ---------------------------------------------------------------------------------


def _usable_cart(session: Session, user_id: int) -> CartView:
    cart = get_cart(session, user_id)
    if not cart.items:
        raise DomainError("EMPTY_CART", "Tu carrito está vacío")
    with_issues = [i for i in cart.items if i.issues]
    if with_issues:
        raise DomainError(
            "CART_HAS_ISSUES",
            "Hay productos del carrito que no se pueden comprar así: revisalos antes de seguir",
            {
                "items": [
                    {"product_id": i.product_id, "name": i.name, "issues": i.issues}
                    for i in with_issues
                ]
            },
        )
    return cart


def _stock(session: Session, product_ids: list[str], *, lock: bool = False):
    """Rows (product_id, warehouse_id, available, pickup_enabled, shipping_enabled).
    With lock=True the inventory rows are locked FOR UPDATE, always in the same order
    (product, warehouse) so two purchases cannot deadlock."""
    stmt = (
        select(
            Inventory.product_id,
            Inventory.warehouse_id,
            Inventory.available_qty,
            Warehouse.pickup_enabled,
            Warehouse.shipping_enabled,
        )
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .where(Inventory.product_id.in_(product_ids))
        .order_by(Inventory.product_id, Inventory.warehouse_id)
    )
    if lock:
        stmt = stmt.with_for_update(of=Inventory)
    return session.execute(stmt).all()


def _allocate(
    rows, method: DeliveryMethod, warehouse_id: str | None, wanted: dict[str, int]
) -> tuple[dict[str, Allocation], list[tuple[str, int, int]]]:
    """Allocation per product, plus the shortfalls as (product_id, requested, available)."""
    allocations: dict[str, Allocation] = {}
    short: list[tuple[str, int, int]] = []
    for product_id, quantity in wanted.items():
        mine = [r for r in rows if r.product_id == product_id]
        if method == DeliveryMethod.SHIPPING:
            stock = {r.warehouse_id: r.available_qty for r in mine if r.shipping_enabled}
            allocation = allocate_shipping(stock, quantity)
            available = sum(max(v, 0) for v in stock.values())
        else:
            stock = {r.warehouse_id: r.available_qty for r in mine if r.pickup_enabled}
            allocation = allocate_pickup(stock, warehouse_id or "", quantity)
            available = max(stock.get(warehouse_id or "", 0), 0)
        if allocation is None:
            short.append((product_id, quantity, available))
        else:
            allocations[product_id] = allocation
    return allocations, short


def _utc(moment: datetime | None) -> datetime | None:
    """The DB stores naive timestamps in UTC (Postgres now()): say so, so the browser shows
    them in the user's time zone."""
    return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


def _warehouse_ref(w: Warehouse) -> WarehouseRef:
    return WarehouseRef(warehouse_id=w.id, name=w.name, city=w.city, department=w.department)


def _pickup_options(session: Session, cart: CartView) -> list[PickupOption]:
    wanted = {i.product_id: i.quantity for i in cart.items}
    names = {i.product_id: i.name for i in cart.items}
    rows = _stock(session, list(wanted))
    options = []
    for w in session.scalars(
        select(Warehouse).where(Warehouse.pickup_enabled.is_(True)).order_by(Warehouse.id)
    ):
        _, short = _allocate(rows, DeliveryMethod.PICKUP, w.id, wanted)
        options.append(
            PickupOption(
                **_warehouse_ref(w).model_dump(),
                can_fulfill=not short,
                missing=[
                    MissingItem(
                        product_id=pid, name=names[pid], requested=requested, available=available
                    )
                    for pid, requested, available in short
                ],
            )
        )
    return sorted(options, key=lambda o: (not o.can_fulfill, o.warehouse_id))


def _lock_order(session: Session, user_id: int, order_id: int) -> Order:
    order = session.scalars(
        select(Order)
        .where(Order.id == order_id, Order.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one_or_none()
    if order is None:
        # Someone else's order looks exactly like a missing one
        raise DomainError("ORDER_NOT_FOUND", "No encontramos esa orden", {"order_id": order_id})
    return order


def _view(session: Session, order: Order) -> OrderView:
    rows = session.execute(
        select(OrderItem, Product.image_url, Category.name)
        .join(Product, Product.id == OrderItem.product_id)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .where(OrderItem.order_id == order.id)
        .order_by(OrderItem.id)
    ).all()
    allocations: dict[int, list[AllocationView]] = {}
    for alloc, warehouse_name in session.execute(
        select(OrderItemAllocation, Warehouse.name)
        .join(Warehouse, Warehouse.id == OrderItemAllocation.warehouse_id)
        .where(OrderItemAllocation.order_item_id.in_([item.id for item, _, _ in rows]))
        .order_by(OrderItemAllocation.warehouse_id)
    ):
        allocations.setdefault(alloc.order_item_id, []).append(
            AllocationView(
                warehouse_id=alloc.warehouse_id,
                warehouse_name=warehouse_name,
                quantity=alloc.quantity,
            )
        )
    warehouse = (
        session.get(Warehouse, order.pickup_warehouse_id) if order.pickup_warehouse_id else None
    )
    return OrderView(
        order_id=order.id,
        code=order.code,
        status=OrderStatus(order.status),
        created_at=_utc(order.created_at),
        confirmed_at=_utc(order.confirmed_at),
        cancelled_at=_utc(order.cancelled_at),
        customer_name=order.customer_name,
        email=order.email,
        delivery_method=DeliveryMethod(order.delivery_method),
        shipping_address=ShippingAddress(**order.shipping_address)
        if order.shipping_address
        else None,
        pickup_warehouse=_warehouse_ref(warehouse) if warehouse else None,
        payment_method=PaymentMethod(order.payment_method),
        currency=order.currency,
        items=[
            OrderItemView(
                product_id=item.product_id,
                name=item.product_name,
                sku=item.sku,
                category=category,
                image_url=image_url,
                unit_price=item.unit_price,
                quantity=item.quantity,
                line_total=item.line_total,
                allocations=allocations.get(item.id, []),
            )
            for item, image_url, category in rows
        ],
        item_count=sum(item.quantity for item, _, _ in rows),
        subtotal=order.subtotal,
        shipping_cost=order.shipping_cost,
        total=order.total,
    )


def _set_totals(order: Order, items: list[OrderItem], policy: ShippingPolicy) -> None:
    order.subtotal = sum((i.line_total for i in items), Decimal("0.00"))
    order.shipping_cost = shipping_cost(
        DeliveryMethod(order.delivery_method), order.subtotal, policy
    )
    order.total = order.subtotal + order.shipping_cost


# --- Checkout --------------------------------------------------------------------------------


def checkout_options(session: Session, user_id: int, policy: ShippingPolicy) -> CheckoutOptions:
    cart = _usable_cart(session, user_id)
    return CheckoutOptions(
        currency=cart.currency,
        subtotal=cart.total,
        item_count=cart.item_count,
        shipping=ShippingQuote(
            cost=shipping_cost(DeliveryMethod.SHIPPING, cart.total, policy),
            base_cost=policy.cost.quantize(CENT),
            free_from=policy.free_from.quantize(CENT),
        ),
        pickup=_pickup_options(session, cart),
        payment_methods=list(PaymentMethod),
    )


def _check_pickup(session: Session, cart: CartView, warehouse_id: str | None) -> Warehouse:
    """The branch exists, has pickup, and has the WHOLE cart. Otherwise PICKUP_UNAVAILABLE
    with what is missing and the branches that can (and shipping as the way out)."""
    warehouse = session.get(Warehouse, warehouse_id) if warehouse_id else None
    if warehouse is None or not warehouse.pickup_enabled:
        valid = session.scalars(
            select(Warehouse.id).where(Warehouse.pickup_enabled.is_(True)).order_by(Warehouse.id)
        ).all()
        raise DomainError(
            "INVALID_INPUT",
            "Esa sucursal no existe o no tiene retiro",
            {
                "field": "pickup_warehouse_id",
                "pickup_warehouse_id": warehouse_id,
                "valid_warehouses": list(valid),
            },
        )
    options = _pickup_options(session, cart)
    chosen = next(o for o in options if o.warehouse_id == warehouse.id)
    if not chosen.can_fulfill:
        raise DomainError(
            "PICKUP_UNAVAILABLE",
            f"{warehouse.name} no tiene stock de todo tu carrito",
            {
                "warehouse_id": warehouse.id,
                "missing": [m.model_dump() for m in chosen.missing],
                "warehouses_that_can": [o.warehouse_id for o in options if o.can_fulfill],
                "suggestion": "SHIPPING",
            },
        )
    return warehouse


class CheckoutHandoff(BaseModel):
    """What the agent's start_checkout leaves for the UI: a "go to checkout" card, with the
    delivery method and branch the user said (editable prefill). Nothing is created or bought."""

    delivery_method: DeliveryMethod | None
    pickup_warehouse: WarehouseRef | None
    currency: str
    item_count: int
    subtotal: Decimal
    shipping_cost: Decimal  # with the chosen method (shipping when none was chosen)
    total: Decimal


def prepare_checkout(
    session: Session,
    user_id: int,
    method: DeliveryMethod | None,
    warehouse_id: str | None,
    policy: ShippingPolicy,
) -> CheckoutHandoff:
    """Checks that the cart can go to checkout (and the branch, if one was named). Creates
    nothing: the order is created by the checkout form, and only its button buys."""
    cart = _usable_cart(session, user_id)
    if warehouse_id and method is None:
        method = DeliveryMethod.PICKUP
    warehouse = None
    if method == DeliveryMethod.PICKUP and warehouse_id:
        warehouse = _check_pickup(session, cart, warehouse_id)
    cost = shipping_cost(method or DeliveryMethod.SHIPPING, cart.total, policy)
    return CheckoutHandoff(
        delivery_method=method,
        pickup_warehouse=_warehouse_ref(warehouse) if warehouse else None,
        currency=cart.currency,
        item_count=cart.item_count,
        subtotal=cart.total,
        shipping_cost=cost,
        total=cart.total + cost,
    )


def create_checkout(
    session: Session, user_id: int, request: CheckoutRequest, policy: ShippingPolicy
) -> OrderView:
    """Order PENDING_CONFIRMATION with the current prices (the quote the user reviews).
    A new checkout replaces the user's previous pending one."""
    cart = _usable_cart(session, user_id)
    wanted = {i.product_id: i.quantity for i in cart.items}
    method = request.delivery_method

    if method == DeliveryMethod.PICKUP:
        _check_pickup(session, cart, request.pickup_warehouse_id)
    else:
        _, short = _allocate(_stock(session, list(wanted)), method, None, wanted)
        if short:
            raise _out_of_stock(_cart_names(cart), short, None)

    session.execute(
        update(Order)
        .where(Order.user_id == user_id, Order.status == OrderStatus.PENDING_CONFIRMATION)
        .values(status=OrderStatus.CANCELLED, cancelled_at=func.now(), updated_at=func.now())
    )
    order = Order(
        user_id=user_id,
        status=OrderStatus.PENDING_CONFIRMATION,
        customer_name=request.customer_name,
        email=request.email,
        delivery_method=method,
        shipping_address=request.shipping_address.model_dump()
        if request.shipping_address
        else None,
        pickup_warehouse_id=request.pickup_warehouse_id,
        payment_method=request.payment_method,
        currency=cart.currency,
        subtotal=Decimal("0.00"),
        shipping_cost=Decimal("0.00"),
        total=Decimal("0.00"),
    )
    session.add(order)
    session.flush()
    items = [
        OrderItem(
            order_id=order.id,
            product_id=i.product_id,
            product_name=i.name,
            sku=i.sku,
            unit_price=i.unit_price,
            quantity=i.quantity,
            line_total=(i.unit_price * i.quantity).quantize(CENT),
        )
        for i in cart.items
    ]
    session.add_all(items)
    _set_totals(order, items, policy)
    session.commit()
    session.refresh(order)  # the code is computed by Postgres
    return _view(session, order)


def _cart_names(cart: CartView) -> dict[str, str]:
    return {i.product_id: i.name for i in cart.items}


def _out_of_stock(
    names: dict[str, str], short: list[tuple[str, int, int]], warehouse: Warehouse | None
) -> DomainError:
    first_id, requested, available = short[0]
    where = f" en {warehouse.name}" if warehouse else ""
    message = (
        f"{names[first_id]} ya no tiene stock{where}"
        if available == 0
        else f"Solo quedan {available} unidades de {names[first_id]}{where} (pediste {requested})"
    )
    return DomainError(
        "OUT_OF_STOCK",
        message,
        {
            "warehouse_id": warehouse.id if warehouse else None,
            "items": [
                {"product_id": pid, "name": names[pid], "requested": req, "available": av}
                for pid, req, av in short
            ],
        },
    )


# --- The purchase ----------------------------------------------------------------------------


def confirm_order(
    session: Session, user_id: int, order_id: int, policy: ShippingPolicy
) -> OrderView:
    """The purchase transaction (docs/PLAN.md §12.1). Revalidates, in this order, the cart,
    the products (active), the prices and the stock, with the rows locked. Any failure rolls
    everything back; a price change updates the pending order so the user confirms again."""
    try:
        order = _lock_order(session, user_id, order_id)
        if order.status == OrderStatus.CONFIRMED:
            # Double click / retried request: the same order, nothing is bought twice
            view = _view(session, order)
            session.rollback()
            return view
        if order.status == OrderStatus.CANCELLED:
            raise DomainError("ORDER_CANCELLED", "Esta orden fue cancelada", {"order_id": order.id})

        items = list(
            session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id).order_by(OrderItem.id)
            )
        )
        wanted = {i.product_id: i.quantity for i in items}
        names = {i.product_id: i.product_name for i in items}

        # 1. The cart is still what the user reviewed (it is locked: no change can slip in)
        cart_id = session.scalar(select(Cart.id).where(Cart.user_id == user_id).with_for_update())
        in_cart = dict(
            session.execute(
                select(CartItem.product_id, CartItem.quantity).where(CartItem.cart_id == cart_id)
            ).all()
        )
        if in_cart != wanted:
            raise DomainError(
                "CART_CHANGED",
                "Tu carrito cambió después del resumen: revisá el checkout de nuevo",
                {"order_id": order.id},
            )

        # 2. Products still active, and 3. prices still the quoted ones (rows locked)
        current = {
            pid: (active, price)
            for pid, active, price in session.execute(
                select(Product.id, Product.active, Price.current_price)
                .join(Price, Price.product_id == Product.id)
                .where(Product.id.in_(list(wanted)))
                .order_by(Product.id)
                .with_for_update(of=Price)
            )
        }
        inactive = [pid for pid in wanted if not current[pid][0]]
        if inactive:
            raise DomainError(
                "INACTIVE",
                f"{names[inactive[0]]} se discontinuó y ya no se puede comprar",
                {"items": [{"product_id": pid, "name": names[pid]} for pid in inactive]},
            )
        changed = [i for i in items if current[i.product_id][1] != i.unit_price]
        if changed:
            changes = [
                {
                    "product_id": i.product_id,
                    "name": i.product_name,
                    "old_price": str(i.unit_price),
                    "new_price": str(current[i.product_id][1]),
                }
                for i in changed
            ]
            for i in changed:
                i.unit_price = current[i.product_id][1]
                i.line_total = (i.unit_price * i.quantity).quantize(CENT)
            _set_totals(order, items, policy)
            order.updated_at = func.now()
            session.commit()  # the pending order now has the new quote; nothing was bought
            session.refresh(order)
            first = changes[0]
            raise DomainError(
                "PRICE_CHANGED",
                f"El precio de {first['name']} cambió de "
                f"{format_usd(Decimal(first['old_price']))} a "
                f"{format_usd(Decimal(first['new_price']))}. Revisá el resumen y confirmá de nuevo",
                {"changes": changes, "order": _view(session, order).model_dump(mode="json")},
            )

        # 4. Stock per warehouse, locked, and the allocation (greedy for shipping)
        method = DeliveryMethod(order.delivery_method)
        allocations, short = _allocate(
            _stock(session, list(wanted), lock=True), method, order.pickup_warehouse_id, wanted
        )
        if short:
            warehouse = (
                session.get(Warehouse, order.pickup_warehouse_id)
                if order.pickup_warehouse_id
                else None
            )
            raise _out_of_stock(names, short, warehouse)

        # 5. Execute: discount on_hand (available_qty is generated) and record where it came from
        for item in items:
            for warehouse_id, quantity in allocations[item.product_id].items():
                done = session.execute(
                    update(Inventory)
                    .where(
                        Inventory.product_id == item.product_id,
                        Inventory.warehouse_id == warehouse_id,
                        Inventory.available_qty >= quantity,
                    )
                    .values(on_hand_qty=Inventory.on_hand_qty - quantity, updated_at=func.now())
                )
                if done.rowcount != 1:  # cannot happen with the lock; defense in depth
                    raise _out_of_stock(names, [(item.product_id, quantity, 0)], None)
                session.add(
                    OrderItemAllocation(
                        order_item_id=item.id, warehouse_id=warehouse_id, quantity=quantity
                    )
                )
        order.status = OrderStatus.CONFIRMED
        order.confirmed_at = func.now()
        order.updated_at = func.now()
        session.execute(delete(CartItem).where(CartItem.cart_id == cart_id))
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(order)
    return _view(session, order)


def cancel_order(session: Session, user_id: int, order_id: int) -> OrderView:
    """Only a pending checkout can be cancelled (nothing was bought). A confirmed order is final."""
    try:
        order = _lock_order(session, user_id, order_id)
        if order.status == OrderStatus.CONFIRMED:
            raise DomainError(
                "ORDER_NOT_CANCELLABLE",
                "Una orden confirmada no se puede cancelar",
                {"order_id": order.id},
            )
        if order.status == OrderStatus.PENDING_CONFIRMATION:
            order.status = OrderStatus.CANCELLED
            order.cancelled_at = func.now()
            order.updated_at = func.now()
        session.commit()
    except Exception:
        session.rollback()
        raise
    session.refresh(order)
    return _view(session, order)


# --- History ---------------------------------------------------------------------------------


def get_order(session: Session, user_id: int, code: str) -> OrderView:
    order = session.scalars(
        select(Order).where(Order.code == code.strip().upper(), Order.user_id == user_id)
    ).one_or_none()
    if order is None:
        raise DomainError("ORDER_NOT_FOUND", "No encontramos esa orden", {"code": code})
    return _view(session, order)


def list_orders(session: Session, user_id: int, limit: int = 20, offset: int = 0) -> OrderList:
    """The user's purchases (CONFIRMED), newest first. Pending and cancelled checkouts are not
    purchases, so they are not listed."""
    if not 1 <= limit <= MAX_ORDERS_PAGE or offset < 0:
        raise DomainError("INVALID_INPUT", f"limit entre 1 y {MAX_ORDERS_PAGE}, offset >= 0")
    where = (Order.user_id == user_id, Order.status == OrderStatus.CONFIRMED)
    total = session.scalar(select(func.count()).select_from(Order).where(*where)) or 0
    orders = list(
        session.scalars(
            select(Order)
            .where(*where)
            .order_by(Order.confirmed_at.desc(), Order.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    items: dict[int, list[tuple[str, int]]] = {}
    for order_id, name, quantity in session.execute(
        select(OrderItem.order_id, OrderItem.product_name, OrderItem.quantity)
        .where(OrderItem.order_id.in_([o.id for o in orders]))
        .order_by(OrderItem.id)
    ):
        items.setdefault(order_id, []).append((name, quantity))
    return OrderList(
        items=[
            OrderSummary(
                order_id=o.id,
                code=o.code,
                status=OrderStatus(o.status),
                created_at=_utc(o.created_at),
                confirmed_at=_utc(o.confirmed_at),
                delivery_method=DeliveryMethod(o.delivery_method),
                item_count=sum(q for _, q in items.get(o.id, [])),
                product_names=[n for n, _ in items.get(o.id, [])][:3],
                currency=o.currency,
                total=o.total,
            )
            for o in orders
        ],
        total=total,
    )
