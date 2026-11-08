"""Validate the sheets (row by row and across sheets) and build the rows to load.

Invalid rows are recorded in the report and dropped; they never abort the ingest.
Rows that depend on a rejected row (e.g. the price of a rejected product) are rejected too.
"""

from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.catalog import EMPTY_SPEC_VALUE
from app.ingest.reader import Records
from app.ingest.report import IngestReport
from app.ingest.schemas import (
    BrandRow,
    CategoryRow,
    InventoryRow,
    PriceRow,
    ProductRow,
    RelationRow,
    SpecRow,
    WarehouseRow,
)

EXCEL_FIRST_DATA_ROW = 2  # row 1 is the header


@dataclass
class CatalogData:
    """Validated rows per table, with keys matching the SQLAlchemy model attributes."""

    brands: list[dict[str, Any]] = field(default_factory=list)
    categories: list[dict[str, Any]] = field(default_factory=list)
    subcategories: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    prices: list[dict[str, Any]] = field(default_factory=list)
    product_specs: list[dict[str, Any]] = field(default_factory=list)
    warehouses: list[dict[str, Any]] = field(default_factory=list)
    inventory: list[dict[str, Any]] = field(default_factory=list)
    product_relations: list[dict[str, Any]] = field(default_factory=list)


def _format_error(error: ValidationError) -> str:
    parts = []
    for e in error.errors():
        loc = ".".join(str(p) for p in e["loc"])
        parts.append(f"{loc}: {e['msg']}" if loc else e["msg"])
    return "; ".join(parts)


def _parse_rows[M: BaseModel](
    sheet: str,
    records: list[dict[str, Any]],
    model: type[M],
    key: Callable[[M], Hashable],
    report: IngestReport,
) -> list[tuple[int, M]]:
    """Parse every record with `model`; reject invalid rows and duplicate keys."""
    stats = report.sheet(sheet)
    stats.read = len(records)
    parsed: list[tuple[int, M]] = []
    seen: set[Hashable] = set()
    for index, record in enumerate(records):
        row_number = index + EXCEL_FIRST_DATA_ROW
        try:
            row = model.model_validate(record)
        except ValidationError as error:
            report.reject(sheet, row_number, _record_key(record), _format_error(error))
            continue
        row_key = key(row)
        if row_key in seen:
            report.reject(sheet, row_number, str(row_key), f"duplicate key {row_key}")
            continue
        seen.add(row_key)
        parsed.append((row_number, row))
    return parsed


def _record_key(record: dict[str, Any]) -> str | None:
    for column in ("product_id", "brand_id", "subcategory_id", "warehouse_id"):
        if record.get(column):
            return str(record[column])
    return None


def validate_catalog(records: Records, report: IngestReport) -> CatalogData:
    data = CatalogData()

    # Brands
    brands = _parse_rows("Brands", records["Brands"], BrandRow, lambda r: r.brand_id, report)
    brand_names = {r.brand_id: r.brand_name for _, r in brands}
    data.brands = [
        {
            "id": r.brand_id,
            "name": r.brand_name,
            "country_of_origin": r.country_of_origin,
            "positioning": r.positioning,
        }
        for _, r in brands
    ]

    # Categories sheet -> categories + subcategories
    subcats = _parse_rows(
        "Categories", records["Categories"], CategoryRow, lambda r: r.subcategory_id, report
    )
    categories: dict[str, CategoryRow] = {}
    subcategory_by_names: dict[tuple[str, str], str] = {}
    for row_number, r in subcats:
        first = categories.setdefault(r.category_id, r)
        if first.category_name != r.category_name:
            report.reject(
                "Categories",
                row_number,
                r.subcategory_id,
                f"category {r.category_id} has two names: "
                f"'{first.category_name}' and '{r.category_name}'",
            )
            continue
        subcategory_by_names[(r.category_name, r.subcategory_name)] = r.subcategory_id
        data.subcategories.append(
            {
                "id": r.subcategory_id,
                "category_id": r.category_id,
                "name": r.subcategory_name,
                "sort_order": r.sort_order,
            }
        )
    data.categories = [
        {"id": c.category_id, "name": c.category_name, "department": c.department}
        for c in categories.values()
    ]

    # Warehouses
    warehouses = _parse_rows(
        "Warehouses", records["Warehouses"], WarehouseRow, lambda r: r.warehouse_id, report
    )
    warehouse_ids = {r.warehouse_id for _, r in warehouses}
    data.warehouses = [
        {
            "id": r.warehouse_id,
            "name": r.warehouse_name,
            "city": r.city,
            "department": r.department,
            "country": r.country,
            "pickup_enabled": r.pickup_enabled,
            "shipping_enabled": r.shipping_enabled,
        }
        for _, r in warehouses
    ]

    # Products
    products = _parse_rows(
        "Products", records["Products"], ProductRow, lambda r: r.product_id, report
    )
    product_ids: set[str] = set()
    skus: set[str] = set()
    for row_number, r in products:
        subcategory_id = subcategory_by_names.get((r.category, r.subcategory))
        if r.brand_id not in brand_names:
            report.reject("Products", row_number, r.product_id, f"unknown brand_id {r.brand_id}")
            continue
        if subcategory_id is None:
            report.reject(
                "Products",
                row_number,
                r.product_id,
                f"unknown category/subcategory '{r.category} / {r.subcategory}'",
            )
            continue
        if r.sku in skus:
            report.reject("Products", row_number, r.product_id, f"duplicate sku {r.sku}")
            continue
        if r.brand and r.brand != brand_names[r.brand_id]:
            report.warn(
                "Products",
                row_number,
                r.product_id,
                f"brand '{r.brand}' differs from {r.brand_id} '{brand_names[r.brand_id]}'",
            )
        product_ids.add(r.product_id)
        skus.add(r.sku)
        data.products.append(
            {
                "id": r.product_id,
                "sku": r.sku,
                "name": r.name,
                "brand_id": r.brand_id,
                "subcategory_id": subcategory_id,
                **r.model_dump(
                    include={
                        "short_description",
                        "description",
                        "recommended_for",
                        "not_recommended_for",
                        "key_features",
                        "tags",
                        "color",
                        "weight_kg",
                        "width_cm",
                        "height_cm",
                        "depth_cm",
                        "warranty_months",
                        "return_days",
                        "rating",
                        "review_count",
                        "launch_date",
                        "active",
                        "image_url",
                    }
                ),
            }
        )
    valid_products = [r for _, r in products if r.product_id in product_ids]

    def require_product(sheet: str, row_number: int, product_id: str) -> bool:
        if product_id in product_ids:
            return True
        report.reject(sheet, row_number, product_id, f"unknown or rejected product {product_id}")
        return False

    # Pricing
    priced: set[str] = set()
    for row_number, r in _parse_rows(
        "Pricing", records["Pricing"], PriceRow, lambda r: r.product_id, report
    ):
        if not require_product("Pricing", row_number, r.product_id):
            continue
        priced.add(r.product_id)
        data.prices.append(
            {
                "product_id": r.product_id,
                "currency": r.currency,
                "list_price": r.list_price,
                "current_price": r.current_price,
                "discount_percent": r.discount_percent,
                "tax_included": r.tax_included,
                "updated_at": r.price_updated_at,
            }
        )
    for product_id in sorted(product_ids - priced):
        report.warn("Pricing", None, product_id, "product has no price (cannot be sold)")

    # Specifications
    empty_specs = 0
    for row_number, r in _parse_rows(
        "Specifications",
        records["Specifications"],
        SpecRow,
        lambda r: (r.product_id, r.attribute_name),
        report,
    ):
        if not require_product("Specifications", row_number, r.product_id):
            continue
        value_text = r.value_text
        if r.is_empty:
            empty_specs += 1
            value_text = EMPTY_SPEC_VALUE
            report.warn(
                "Specifications",
                row_number,
                r.product_id,
                f"'{r.attribute_name}' has no value: loaded as {EMPTY_SPEC_VALUE}",
            )
        data.product_specs.append(
            {
                "product_id": r.product_id,
                "attribute_name": r.attribute_name,
                "attribute_group": r.attribute_group,
                "value_text": value_text,
                "value_number": r.value_number,
                "unit": r.unit,
            }
        )

    # Inventory
    available_by_product: Counter[str] = Counter()
    for row_number, r in _parse_rows(
        "Inventory",
        records["Inventory"],
        InventoryRow,
        lambda r: (r.product_id, r.warehouse_id),
        report,
    ):
        if not require_product("Inventory", row_number, r.product_id):
            continue
        if r.warehouse_id not in warehouse_ids:
            report.reject(
                "Inventory", row_number, r.product_id, f"unknown warehouse {r.warehouse_id}"
            )
            continue
        available_by_product[r.product_id] += r.available_qty
        data.inventory.append(
            {
                "product_id": r.product_id,
                "warehouse_id": r.warehouse_id,
                "on_hand_qty": r.on_hand_qty,
                "reserved_qty": r.reserved_qty,
                "updated_at": r.inventory_updated_at,
            }
        )

    # Relations
    for row_number, r in _parse_rows(
        "Relations",
        records["Relations"],
        RelationRow,
        lambda r: (r.product_id, r.related_product_id, r.relation_type),
        report,
    ):
        if not require_product("Relations", row_number, r.product_id):
            continue
        if not require_product("Relations", row_number, r.related_product_id):
            continue
        data.product_relations.append(r.model_dump())

    _set_valid_counts(report, data)
    report.findings = _findings(valid_products, available_by_product, empty_specs)
    return data


def _set_valid_counts(report: IngestReport, data: CatalogData) -> None:
    report.sheet("Brands").valid = len(data.brands)
    report.sheet("Categories").valid = len(data.subcategories)
    report.sheet("Warehouses").valid = len(data.warehouses)
    report.sheet("Products").valid = len(data.products)
    report.sheet("Pricing").valid = len(data.prices)
    report.sheet("Specifications").valid = len(data.product_specs)
    report.sheet("Inventory").valid = len(data.inventory)
    report.sheet("Relations").valid = len(data.product_relations)


def _findings(
    products: list[ProductRow], available: Counter[str], empty_specs: int
) -> dict[str, Any]:
    """Data-quality facts that drive design decisions (docs/PLAN.md §2.1)."""
    name_counts = Counter(p.name for p in products)
    duplicated_names = sorted(name for name, count in name_counts.items() if count > 1)
    return {
        "inactive_products": sorted(p.product_id for p in products if not p.active),
        "out_of_stock_products": sorted(
            p.product_id for p in products if available.get(p.product_id, 0) == 0
        ),
        "duplicate_names": [
            {"name": name, "product_ids": sorted(p.product_id for p in products if p.name == name)}
            for name in duplicated_names
        ],
        "empty_specs": empty_specs,
    }
