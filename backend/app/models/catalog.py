"""Catalog tables, loaded from the Excel dataset (docs/PLAN.md §7.1)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Computed,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    column,
    table,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

RELATION_TYPES = ("alternative_to", "accessory_for", "often_bought_with")


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # BR001
    name: Mapped[str] = mapped_column(Text)
    country_of_origin: Mapped[str | None] = mapped_column(Text)
    positioning: Mapped[str | None] = mapped_column(Text)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # CAT01
    name: Mapped[str] = mapped_column(Text, unique=True)
    department: Mapped[str | None] = mapped_column(Text)


class Subcategory(Base):
    __tablename__ = "subcategories"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # SUB001
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"))
    name: Mapped[str] = mapped_column(Text)
    sort_order: Mapped[int]


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)  # MN-HDP-0004
    sku: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(Text)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id"))
    subcategory_id: Mapped[str] = mapped_column(ForeignKey("subcategories.id"))
    short_description: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    recommended_for: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    not_recommended_for: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    key_features: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    color: Mapped[str | None] = mapped_column(Text)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    width_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    height_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    depth_cm: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    warranty_months: Mapped[int | None]
    return_days: Mapped[int | None]
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    review_count: Mapped[int | None]
    launch_date: Mapped[date | None]
    active: Mapped[bool]
    image_url: Mapped[str | None] = mapped_column(Text)
    # Full-text search over the English catalog text (used by hybrid search, §9.5)
    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(name, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(short_description, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'C')",
            persisted=True,
        ),
    )

    __table_args__ = (
        Index("ix_products_recommended_for", "recommended_for", postgresql_using="gin"),
        Index("ix_products_search_tsv", "search_tsv", postgresql_using="gin"),
        Index("ix_products_subcategory_id", "subcategory_id"),
        Index("ix_products_brand_id", "brand_id"),
    )


class Price(Base):
    """Separate table: price is dynamic data (it is never embedded)."""

    __tablename__ = "prices"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    list_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    current_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    discount_percent: Mapped[int]
    tax_included: Mapped[bool]
    updated_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint("list_price > 0 AND current_price > 0", name="ck_prices_positive"),
        CheckConstraint("discount_percent BETWEEN 0 AND 100", name="ck_prices_discount_range"),
    )


class ProductSpec(Base):
    """Specs in EAV format: one row per (product, attribute)."""

    __tablename__ = "product_specs"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    attribute_name: Mapped[str] = mapped_column(Text, primary_key=True)
    attribute_group: Mapped[str | None] = mapped_column(Text)
    value_text: Mapped[str | None] = mapped_column(Text)
    value_number: Mapped[Decimal | None] = mapped_column(Numeric(12, 3))
    unit: Mapped[str | None] = mapped_column(Text)


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # WH-MVD-CEN
    name: Mapped[str] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    pickup_enabled: Mapped[bool]
    shipping_enabled: Mapped[bool]


class Inventory(Base):
    """Stock per warehouse. The In/Low/Out status is computed, never stored."""

    __tablename__ = "inventory"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    warehouse_id: Mapped[str] = mapped_column(ForeignKey("warehouses.id"), primary_key=True)
    on_hand_qty: Mapped[int]
    reserved_qty: Mapped[int]
    available_qty: Mapped[int] = mapped_column(
        Computed("on_hand_qty - reserved_qty", persisted=True)
    )
    updated_at: Mapped[datetime | None]

    __table_args__ = (
        CheckConstraint(
            "on_hand_qty >= reserved_qty AND reserved_qty >= 0", name="ck_inventory_quantities"
        ),
    )


class ProductRelation(Base):
    __tablename__ = "product_relations"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    related_product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    strength: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))

    __table_args__ = (
        CheckConstraint("product_id <> related_product_id", name="ck_relations_no_self"),
        CheckConstraint(
            "relation_type IN ('alternative_to', 'accessory_for', 'often_bought_with')",
            name="ck_relations_type",
        ),
    )


# Read-only view created in migration 0001: total available stock and its status per product.
# Lightweight construct (not in Base.metadata) because it is not a table we write to.
product_availability = table(
    "product_availability",
    column("product_id", String),
    column("available", Integer),
    column("status", String),
)
