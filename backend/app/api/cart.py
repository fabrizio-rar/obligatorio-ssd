"""Cart endpoints (login required). Only HTTP here: the rules are in domain/cart.py.
Every mutation returns the updated cart, so the UI does not need a second request."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import CurrentUser
from app.db import get_db
from app.domain import cart
from app.domain.cart import CartView

router = APIRouter(prefix="/cart", tags=["cart"])
Db = Annotated[Session, Depends(get_db)]


class AddItem(BaseModel):
    product_id: str
    quantity: int = 1


class SetQuantity(BaseModel):
    quantity: int


@router.get("", response_model=CartView)
def get_cart(user: CurrentUser, db: Db):
    return cart.get_cart(db, user.id)


@router.post("/items", response_model=CartView)
def add_item(body: AddItem, user: CurrentUser, db: Db):
    return cart.add_item(db, user.id, body.product_id.strip(), body.quantity)


@router.patch("/items/{product_id}", response_model=CartView)
def set_quantity(product_id: str, body: SetQuantity, user: CurrentUser, db: Db):
    return cart.set_quantity(db, user.id, product_id, body.quantity)


@router.delete("/items/{product_id}", response_model=CartView)
def remove_item(product_id: str, user: CurrentUser, db: Db):
    return cart.remove_item(db, user.id, product_id)


@router.delete("", response_model=CartView)
def clear_cart(user: CurrentUser, db: Db):
    return cart.clear_cart(db, user.id)
