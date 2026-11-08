"""Catalog rules and queries (pure business logic: no LLM, no HTTP).

Used by the agent's get_product tool and, later, by GET /api/products/{id} (N4):
the UI and the agent run the SAME functions (AGENTS.md rule 1).
"""

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.domain.inventory import StockStatus, stock_status
from app.models import (
    Brand,
    Category,
    Inventory,
    Price,
    Product,
    ProductSpec,
    Subcategory,
    Warehouse,
)

# Value stored for a spec that has neither value_text nor value_number in the dataset.
# It is shown as "N/D" and never inferred (docs/PLAN.md §2.1).
EMPTY_SPEC_VALUE = "N/D"

MAX_NAME_MATCHES = 5


class ProductStatus(StrEnum):
    AVAILABLE = "available"
    OUT_OF_STOCK = "out_of_stock"
    DISCONTINUED = "discontinued"  # active = false: not shown, not searched, not sold


class ProductMatch(BaseModel):
    product_id: str
    name: str
    sku: str
    category: str
    active: bool


class SpecValue(BaseModel):
    group: str | None
    name: str
    value: str  # "22 h", "Yes", or "N/D" when the dataset has no value
    available: bool  # False for N/D


class WarehouseStock(BaseModel):
    warehouse_id: str
    name: str
    city: str | None
    available: int
    pickup_enabled: bool


class ProductDetail(BaseModel):
    product_id: str
    name: str
    sku: str
    category: str
    subcategory: str
    status: ProductStatus
    # Everything below is None/empty for discontinued products: they are not sold,
    # so neither the UI nor the agent gets data to offer them.
    brand: str | None = None
    brand_positioning: str | None = None
    short_description: str | None = None
    description: str | None = None
    key_features: list[str] = []
    recommended_for: list[str] = []
    not_recommended_for: list[str] = []
    color: str | None = None
    weight_kg: Decimal | None = None
    dimensions_cm: str | None = None  # "W x H x D"
    warranty_months: int | None = None
    return_days: int | None = None
    rating: Decimal | None = None
    review_count: int | None = None
    currency: str | None = None
    current_price: Decimal | None = None
    list_price: Decimal | None = None
    discount_percent: int | None = None
    available: int | None = None
    stock_status: StockStatus | None = None
    stock_by_warehouse: list[WarehouseStock] = []
    specs: list[SpecValue] = []


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def find_products_by_name(session: Session, name: str) -> list[ProductMatch]:
    """Products whose name matches, INCLUDING inactive ones (to say "discontinued").
    1. exact match ignoring case and spaces; 2. otherwise, names containing every word."""
    wanted = _normalize(name)
    if not wanted:
        return []
    stmt = (
        select(Product.id, Product.name, Product.sku, Category.name, Product.active)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .order_by(Product.active.desc(), Product.name, Product.id)
    )
    normalized_name = func.lower(func.regexp_replace(Product.name, r"\s+", " ", "g"))
    rows = session.execute(stmt.where(normalized_name == wanted)).all()
    if not rows:
        partial = stmt
        for word in wanted.split(" "):
            partial = partial.where(normalized_name.contains(word, autoescape=True))
        rows = session.execute(partial.limit(MAX_NAME_MATCHES)).all()
    return [
        ProductMatch(product_id=pid, name=pname, sku=sku, category=cat, active=active)
        for pid, pname, sku, cat, active in rows[:MAX_NAME_MATCHES]
    ]


def format_number(value: Decimal) -> str:
    """Decimal('22.000') -> '22', Decimal('0.500') -> '0.5'."""
    return f"{value.normalize():f}"


def _spec_value(spec: ProductSpec) -> SpecValue:
    if spec.value_text is not None and spec.value_text != EMPTY_SPEC_VALUE:
        value, available = spec.value_text, True
    elif spec.value_number is not None:
        value, available = format_number(spec.value_number), True
    else:
        value, available = EMPTY_SPEC_VALUE, False
    if available and spec.unit:
        value = f"{value} {spec.unit}"
    return SpecValue(
        group=spec.attribute_group, name=spec.attribute_name, value=value, available=available
    )


def get_product_detail(session: Session, product_id: str) -> ProductDetail:
    """Full product sheet with CURRENT price and stock per warehouse, read from the DB.
    Raises DomainError NOT_FOUND."""
    row = session.execute(
        select(Product, Brand, Subcategory.name, Category.name)
        .join(Brand, Brand.id == Product.brand_id)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .where(Product.id == product_id)
    ).first()
    if row is None:
        raise DomainError(
            "NOT_FOUND", f"Product {product_id} does not exist", {"product_id": product_id}
        )
    product, brand, subcategory, category = row
    base = {
        "product_id": product.id,
        "name": product.name,
        "sku": product.sku,
        "category": category,
        "subcategory": subcategory,
    }
    if not product.active:
        return ProductDetail(**base, status=ProductStatus.DISCONTINUED)

    stock = [
        WarehouseStock(
            warehouse_id=wh.id,
            name=wh.name,
            city=wh.city,
            available=available,
            pickup_enabled=wh.pickup_enabled,
        )
        for wh, available in session.execute(
            select(Warehouse, Inventory.available_qty)
            .join(Inventory, Inventory.warehouse_id == Warehouse.id)
            .where(Inventory.product_id == product.id)
            .order_by(Warehouse.id)
        )
    ]
    total = sum(w.available for w in stock)
    price = session.get(Price, product.id)
    specs = session.scalars(
        select(ProductSpec)
        .where(ProductSpec.product_id == product.id)
        .order_by(ProductSpec.attribute_group, ProductSpec.attribute_name)
    )
    dims = (product.width_cm, product.height_cm, product.depth_cm)
    return ProductDetail(
        **base,
        status=ProductStatus.AVAILABLE if total > 0 else ProductStatus.OUT_OF_STOCK,
        brand=brand.name,
        brand_positioning=brand.positioning,
        short_description=product.short_description,
        description=product.description,
        key_features=product.key_features,
        recommended_for=product.recommended_for,
        not_recommended_for=product.not_recommended_for,
        color=product.color,
        weight_kg=product.weight_kg,
        dimensions_cm=" x ".join(format_number(d) for d in dims) if all(dims) else None,
        warranty_months=product.warranty_months,
        return_days=product.return_days,
        rating=product.rating,
        review_count=product.review_count,
        currency=price.currency if price else None,
        current_price=price.current_price if price else None,
        list_price=price.list_price if price else None,
        discount_percent=price.discount_percent if price else None,
        available=total,
        stock_status=stock_status(total),
        stock_by_warehouse=stock,
        specs=[_spec_value(s) for s in specs],
    )
