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
    ProductRelation,
    ProductSpec,
    Subcategory,
    Warehouse,
)
from app.models.catalog import product_availability

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
    image_url: str | None = None
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
        image_url=product.image_url,
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


# --- Listing and cards (catalog page, chat cards) ---------------------------------------------

MAX_PAGE_SIZE = 60
MAX_CARD_IDS = 20


class ProductCard(BaseModel):
    """What a product card needs. Price and stock are read from the DB right now."""

    product_id: str
    sku: str
    name: str
    brand: str
    category: str
    subcategory: str
    image_url: str | None
    currency: str
    current_price: Decimal
    list_price: Decimal
    discount_percent: int
    available: int
    stock_status: StockStatus
    rating: Decimal | None
    review_count: int | None


class ProductPage(BaseModel):
    items: list[ProductCard]
    page: int
    page_size: int
    total: int
    total_pages: int


def _card_query():
    return (
        select(
            Product,
            Brand.name,
            Category.name,
            Subcategory.name,
            Price,
            product_availability.c.available,
        )
        .join(Brand, Brand.id == Product.brand_id)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .join(Price, Price.product_id == Product.id)
        .join(product_availability, product_availability.c.product_id == Product.id)
        .where(Product.active.is_(True))  # inactive: not shown, even with stock (rule 6)
    )


def _to_card(row) -> ProductCard:
    product, brand, category, subcategory, price, available = row
    return ProductCard(
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        brand=brand,
        category=category,
        subcategory=subcategory,
        image_url=product.image_url,
        currency=price.currency,
        current_price=price.current_price,
        list_price=price.list_price,
        discount_percent=price.discount_percent,
        available=available,
        stock_status=stock_status(available),
        rating=product.rating,
        review_count=product.review_count,
    )


class ProductSort(StrEnum):
    DEFAULT = "default"  # category display order, then name
    NAME_ASC = "name_asc"
    NAME_DESC = "name_desc"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"


def list_products(
    session: Session,
    category: str | None = None,
    page: int = 1,
    page_size: int = 24,
    *,
    brand: str | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    in_stock: bool = False,
    sort: ProductSort = ProductSort.DEFAULT,
) -> ProductPage:
    """Active products, paginated, with optional filters (category, brand, current price
    range, only with stock). Default order: category (its display order), then name. Every
    order ends with the product ID, so pages are stable (no product repeats or goes missing
    across pages). An unknown brand simply matches nothing."""
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise DomainError("INVALID_INPUT", f"page >= 1 and page_size between 1 and {MAX_PAGE_SIZE}")
    if any(p is not None and p < 0 for p in (min_price, max_price)):
        raise DomainError("INVALID_INPUT", "Prices cannot be negative")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise DomainError(
            "INVALID_INPUT",
            "min_price cannot be greater than max_price",
            {"min_price": str(min_price), "max_price": str(max_price)},
        )
    stmt = _card_query()
    if category is not None:
        stmt = stmt.where(Category.name == category)
    if brand is not None:
        stmt = stmt.where(Brand.name == brand)
    if min_price is not None:
        stmt = stmt.where(Price.current_price >= min_price)
    if max_price is not None:
        stmt = stmt.where(Price.current_price <= max_price)
    if in_stock:
        stmt = stmt.where(product_availability.c.available > 0)
    total = session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = session.execute(
        stmt.order_by(*_ORDER[sort], Product.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ProductPage(
        items=[_to_card(r) for r in rows],
        page=page,
        page_size=page_size,
        total=total,
        total_pages=max(1, -(-total // page_size)),
    )


_ORDER = {
    ProductSort.DEFAULT: (Category.id, Subcategory.sort_order, Product.name),
    ProductSort.NAME_ASC: (func.lower(Product.name),),
    ProductSort.NAME_DESC: (func.lower(Product.name).desc(),),
    ProductSort.PRICE_ASC: (Price.current_price, func.lower(Product.name)),
    ProductSort.PRICE_DESC: (Price.current_price.desc(), func.lower(Product.name)),
}


def product_cards(session: Session, product_ids: list[str]) -> list[ProductCard]:
    """Cards for the given IDs, in the same order (chat cards). Unknown or inactive IDs
    are skipped: the UI never renders a product that is not for sale."""
    ids = list(dict.fromkeys(product_ids))[:MAX_CARD_IDS]
    if not ids:
        return []
    by_id = {
        card.product_id: card
        for card in map(_to_card, session.execute(_card_query().where(Product.id.in_(ids))))
    }
    return [by_id[pid] for pid in ids if pid in by_id]


# --- Categories and warehouses ----------------------------------------------------------------


class CategoryOut(BaseModel):
    category_id: str
    name: str
    subcategories: list[str]
    product_count: int  # active products


class BrandOut(BaseModel):
    brand_id: str
    name: str
    positioning: str | None
    product_count: int  # active products (in the category, when filtered)


class WarehouseOut(BaseModel):
    warehouse_id: str
    name: str
    city: str | None
    department: str | None
    pickup_enabled: bool
    shipping_enabled: bool


def list_categories(session: Session) -> list[CategoryOut]:
    counts = dict(
        session.execute(
            select(Subcategory.category_id, func.count(Product.id))
            .join(Product, Product.subcategory_id == Subcategory.id)
            .where(Product.active.is_(True))
            .group_by(Subcategory.category_id)
        ).all()
    )
    subs: dict[str, list[str]] = {}
    for sub in session.scalars(select(Subcategory).order_by(Subcategory.sort_order)):
        subs.setdefault(sub.category_id, []).append(sub.name)
    return [
        CategoryOut(
            category_id=c.id,
            name=c.name,
            subcategories=subs.get(c.id, []),
            product_count=counts.get(c.id, 0),
        )
        for c in session.scalars(select(Category).order_by(Category.id))
    ]


def list_brands(session: Session, category: str | None = None) -> list[BrandOut]:
    """Brands with at least one active product (in `category`, if given), by name. For the
    catalog's brand filter: the UI never offers a brand that would return nothing."""
    stmt = (
        select(Brand, func.count(Product.id))
        .join(Product, Product.brand_id == Brand.id)
        .where(Product.active.is_(True))
        .group_by(Brand.id)
        .order_by(Brand.name)
    )
    if category is not None:
        stmt = (
            stmt.join(Subcategory, Subcategory.id == Product.subcategory_id)
            .join(Category, Category.id == Subcategory.category_id)
            .where(Category.name == category)
        )
    return [
        BrandOut(brand_id=b.id, name=b.name, positioning=b.positioning, product_count=n)
        for b, n in session.execute(stmt)
    ]


def list_warehouses(session: Session) -> list[WarehouseOut]:
    return [
        WarehouseOut(
            warehouse_id=w.id,
            name=w.name,
            city=w.city,
            department=w.department,
            pickup_enabled=w.pickup_enabled,
            shipping_enabled=w.shipping_enabled,
        )
        for w in session.scalars(select(Warehouse).order_by(Warehouse.id))
    ]


# --- Related products (docs/plans/related-and-compare-tools.md, step 1) ----------------------


class RelationType(StrEnum):
    ALTERNATIVE_TO = "alternative_to"
    ACCESSORY_FOR = "accessory_for"
    OFTEN_BOUGHT_WITH = "often_bought_with"


class RelatedProduct(ProductCard):
    relation_type: RelationType
    strength: Decimal | None


class RelatedResult(BaseModel):
    items: list[RelatedProduct]
    filtered_out: dict[str, int]  # {"inactive": n, "out_of_stock": n}


def get_related(
    session: Session,
    product_id: str,
    relation_type: RelationType,
    in_stock_only: bool = True,
) -> RelatedResult:
    """Related products from product_relations. The related one is related_product_id:
    for accessory_for, "laptop -> webcam" means the webcam is an accessory of the laptop.
    Inactive products are always excluded; out of stock ones too if in_stock_only.
    Works for a discontinued source too ("that one is gone, look at these")."""
    if session.get(Product, product_id) is None:
        raise DomainError(
            "NOT_FOUND", f"Product {product_id} does not exist", {"product_id": product_id}
        )
    relations = session.execute(
        select(ProductRelation.related_product_id, ProductRelation.strength, Product.active)
        .join(Product, Product.id == ProductRelation.related_product_id)
        .where(
            ProductRelation.product_id == product_id,
            ProductRelation.relation_type == relation_type.value,
        )
        .order_by(ProductRelation.strength.desc(), ProductRelation.related_product_id)
    ).all()
    filtered = {"inactive": 0, "out_of_stock": 0}
    cards = {c.product_id: c for c in product_cards(session, [r[0] for r in relations])}
    items = []
    for related_id, strength, active in relations:
        if not active:
            filtered["inactive"] += 1
            continue
        card = cards[related_id]
        if in_stock_only and card.available == 0:
            filtered["out_of_stock"] += 1
            continue
        items.append(
            RelatedProduct(**card.model_dump(), relation_type=relation_type, strength=strength)
        )
    return RelatedResult(items=items, filtered_out=filtered)
