"""Build the text that gets embedded for each product (docs/PLAN.md §9.2).

One document per product, in English like the catalog. It only holds STATIC data:
price, stock and rating change and are always read from the DB, never from the vector.
Pure functions: no DB, no API.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.domain.catalog import EMPTY_SPEC_VALUE


@dataclass(frozen=True)
class SpecText:
    group: str | None
    name: str
    value_text: str | None
    value_number: Decimal | None
    unit: str | None


@dataclass(frozen=True)
class ProductText:
    """Everything the document needs, already joined (brand, category, specs)."""

    product_id: str
    name: str
    brand: str
    brand_positioning: str | None
    category: str
    subcategory: str
    short_description: str | None = None
    description: str | None = None
    key_features: list[str] = field(default_factory=list)
    recommended_for: list[str] = field(default_factory=list)
    not_recommended_for: list[str] = field(default_factory=list)
    specs: list[SpecText] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def format_number(value: Decimal) -> str:
    """Decimal('22.000') -> '22', Decimal('0.500') -> '0.5'."""
    return f"{value.normalize():f}"


def format_spec(spec: SpecText) -> str | None:
    """'Battery Life: 22 h'. Empty specs (N/D) are skipped: they carry no meaning."""
    if spec.value_text is not None and spec.value_text != EMPTY_SPEC_VALUE:
        value = spec.value_text
    elif spec.value_number is not None:
        value = format_number(spec.value_number)
    else:
        return None
    if spec.unit:
        value = f"{value} {spec.unit}"
    return f"{spec.name}: {value}"


def build_document(product: ProductText) -> str:
    """Deterministic: the same product always gives the same text (and the same hash)."""
    brand = product.brand
    if product.brand_positioning:
        brand = f"{brand} ({product.brand_positioning})"

    specs = sorted(product.specs, key=lambda s: (s.group or "", s.name))
    spec_parts = [text for text in (format_spec(s) for s in specs) if text]

    lines = [
        ("Product", product.name),
        ("Brand", brand),
        ("Category", f"{product.category} > {product.subcategory}"),
        ("Summary", product.short_description),
        ("Description", product.description),
        ("Key features", "; ".join(product.key_features)),
        ("Recommended for", "; ".join(product.recommended_for)),
        ("Not recommended for", "; ".join(product.not_recommended_for)),
        ("Specs", "; ".join(spec_parts)),
        ("Tags", "; ".join(product.tags)),
    ]
    # Empty fields are left out instead of writing "Not recommended for: "
    return "\n".join(f"{label}: {value}" for label, value in lines if value)
