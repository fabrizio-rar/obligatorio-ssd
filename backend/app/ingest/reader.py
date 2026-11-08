"""Read the Excel dataset into one list of clean records per sheet."""

from pathlib import Path
from typing import Any

import pandas as pd

from app.ingest.normalize import clean_record

# Expected sheets and the columns the ingest needs from each one
REQUIRED_COLUMNS: dict[str, list[str]] = {
    "Brands": ["brand_id", "brand_name", "country_of_origin", "positioning"],
    "Categories": [
        "category_id",
        "category_name",
        "subcategory_id",
        "subcategory_name",
        "department",
        "sort_order",
    ],
    "Warehouses": [
        "warehouse_id",
        "warehouse_name",
        "city",
        "department",
        "country",
        "pickup_enabled",
        "shipping_enabled",
    ],
    "Products": [
        "product_id",
        "sku",
        "name",
        "brand",
        "brand_id",
        "category",
        "subcategory",
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
    ],
    "Pricing": [
        "product_id",
        "currency",
        "list_price",
        "current_price",
        "discount_percent",
        "tax_included",
        "price_updated_at",
    ],
    "Specifications": [
        "product_id",
        "attribute_group",
        "attribute_name",
        "value_text",
        "value_number",
        "unit",
    ],
    "Inventory": [
        "product_id",
        "warehouse_id",
        "on_hand_qty",
        "reserved_qty",
        "available_qty",
        "inventory_status",
        "inventory_updated_at",
    ],
    "Relations": ["product_id", "related_product_id", "relation_type", "strength"],
}

Records = dict[str, list[dict[str, Any]]]


class DatasetError(Exception):
    """The file cannot be ingested at all (missing file, sheet or column)."""


def frames_to_records(frames: dict[str, pd.DataFrame]) -> Records:
    """Check the structure and convert every sheet into a list of clean dicts."""
    records: Records = {}
    for sheet, columns in REQUIRED_COLUMNS.items():
        if sheet not in frames:
            raise DatasetError(f"Missing sheet: {sheet}")
        missing = [c for c in columns if c not in frames[sheet].columns]
        if missing:
            raise DatasetError(f"Sheet {sheet} is missing columns: {', '.join(missing)}")
        df = frames[sheet][columns].astype(object)
        records[sheet] = [clean_record(row) for row in df.to_dict(orient="records")]
    return records


def read_workbook(path: Path) -> Records:
    if not path.exists():
        raise DatasetError(f"Dataset not found: {path}")
    return frames_to_records(pd.read_excel(path, sheet_name=None))
