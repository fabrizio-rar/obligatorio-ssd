"""Pydantic models for one row of each sheet. Row-level rules live here;
cross-sheet rules (foreign keys, duplicates) live in validate.py."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.domain.inventory import StockStatus, stock_status
from app.ingest.normalize import split_list, to_date

# Max allowed gap between current_price and list_price * (1 - discount): rounding to cents
PRICE_TOLERANCE = Decimal("0.01")

StrList = Annotated[list[str], BeforeValidator(split_list)]
NonNegDecimal = Annotated[Decimal, Field(ge=0)]
NonNegInt = Annotated[int, Field(ge=0)]
OptionalDate = Annotated[date | None, BeforeValidator(to_date)]


class Row(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class BrandRow(Row):
    brand_id: str
    brand_name: str
    country_of_origin: str | None = None
    positioning: str | None = None


class CategoryRow(Row):
    category_id: str
    category_name: str
    subcategory_id: str
    subcategory_name: str
    department: str | None = None
    sort_order: int


class WarehouseRow(Row):
    warehouse_id: str
    warehouse_name: str
    city: str | None = None
    department: str | None = None
    country: str | None = None
    pickup_enabled: bool
    shipping_enabled: bool


class ProductRow(Row):
    product_id: str
    sku: str
    name: str
    brand: str | None = None
    brand_id: str
    category: str
    subcategory: str
    short_description: str | None = None
    description: str | None = None
    recommended_for: StrList = []
    not_recommended_for: StrList = []
    key_features: StrList = []
    tags: StrList = []
    color: str | None = None
    weight_kg: NonNegDecimal | None = None
    width_cm: NonNegDecimal | None = None
    height_cm: NonNegDecimal | None = None
    depth_cm: NonNegDecimal | None = None
    warranty_months: NonNegInt | None = None
    return_days: NonNegInt | None = None
    rating: Annotated[Decimal, Field(ge=0, le=5)] | None = None
    review_count: NonNegInt | None = None
    launch_date: OptionalDate = None
    active: bool
    image_url: str | None = None


class PriceRow(Row):
    product_id: str
    currency: str = Field(min_length=3, max_length=3)
    list_price: Annotated[Decimal, Field(gt=0)]
    current_price: Annotated[Decimal, Field(gt=0)]
    discount_percent: Annotated[int, Field(ge=0, le=100)]
    tax_included: bool
    price_updated_at: datetime | None = None

    @model_validator(mode="after")
    def current_matches_discount(self) -> "PriceRow":
        expected = self.list_price * (100 - self.discount_percent) / 100
        if abs(expected - self.current_price) > PRICE_TOLERANCE:
            raise ValueError(
                f"current_price {self.current_price} != list_price {self.list_price} "
                f"x (1 - {self.discount_percent}%) = {expected:.2f}"
            )
        return self


class SpecRow(Row):
    product_id: str
    attribute_group: str | None = None
    attribute_name: str
    value_text: str | None = None
    value_number: Decimal | None = None
    unit: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.value_text is None and self.value_number is None


class InventoryRow(Row):
    product_id: str
    warehouse_id: str
    on_hand_qty: NonNegInt
    reserved_qty: NonNegInt
    available_qty: int
    inventory_status: StockStatus
    inventory_updated_at: datetime | None = None

    @model_validator(mode="after")
    def consistent_quantities(self) -> "InventoryRow":
        if self.reserved_qty > self.on_hand_qty:
            raise ValueError(f"reserved_qty {self.reserved_qty} > on_hand_qty {self.on_hand_qty}")
        if self.available_qty != self.on_hand_qty - self.reserved_qty:
            raise ValueError(
                f"available_qty {self.available_qty} != on_hand_qty - reserved_qty "
                f"({self.on_hand_qty} - {self.reserved_qty})"
            )
        if self.inventory_status != stock_status(self.available_qty):
            raise ValueError(
                f"inventory_status '{self.inventory_status}' does not match "
                f"available_qty {self.available_qty}"
            )
        return self


class RelationRow(Row):
    product_id: str
    related_product_id: str
    relation_type: Literal["alternative_to", "accessory_for", "often_bought_with"]
    strength: Annotated[Decimal, Field(ge=0, le=1)] | None = None

    @model_validator(mode="after")
    def not_self_related(self) -> "RelationRow":
        if self.product_id == self.related_product_id:
            raise ValueError("a product cannot be related to itself")
        return self
