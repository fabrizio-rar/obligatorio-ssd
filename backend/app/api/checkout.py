"""Checkout and order endpoints (login required). Only HTTP here: the rules and the purchase
transaction are in domain/checkout.py. The purchase is ONLY POST /orders/{id}/confirm, a UI
button: no agent tool calls it (AGENTS.md rule 2)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.config import get_settings
from app.db import get_db
from app.domain import checkout
from app.domain.checkout import (
    MAX_ORDERS_PAGE,
    CheckoutOptions,
    CheckoutRequest,
    OrderList,
    OrderView,
    ShippingPolicy,
)

router = APIRouter(tags=["checkout"])
Db = Annotated[Session, Depends(get_db)]


def _policy() -> ShippingPolicy:
    settings = get_settings()
    return ShippingPolicy(
        cost=settings.shipping_cost_usd, free_from=settings.free_shipping_from_usd
    )


@router.get("/checkout/options", response_model=CheckoutOptions)
def checkout_options(user: CurrentUser, db: Db):
    """Pickup branches (with can_fulfill / missing for the current cart), shipping cost and
    payment methods: everything the checkout form needs."""
    return checkout.checkout_options(db, user.id, _policy())


@router.post("/checkout", response_model=OrderView, status_code=status.HTTP_201_CREATED)
def create_checkout(body: CheckoutRequest, user: CurrentUser, db: Db):
    """Order PENDING_CONFIRMATION with the quoted prices. Nothing is bought yet."""
    return checkout.create_checkout(db, user.id, body, _policy())


@router.post("/orders/{order_id}/confirm", response_model=OrderView)
def confirm_order(order_id: int, user: CurrentUser, db: Db):
    """The purchase transaction (docs/PLAN.md §12.1). Idempotent."""
    return checkout.confirm_order(db, user.id, order_id, _policy())


@router.post("/orders/{order_id}/cancel", response_model=OrderView)
def cancel_order(order_id: int, user: CurrentUser, db: Db):
    return checkout.cancel_order(db, user.id, order_id)


@router.get("/orders", response_model=OrderList)
def list_orders(
    user: CurrentUser,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=MAX_ORDERS_PAGE)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return checkout.list_orders(db, user.id, limit, offset)


@router.get("/orders/{code}", response_model=OrderView)
def get_order(code: str, user: CurrentUser, db: Db):
    return checkout.get_order(db, user.id, code)
