"""Side-by-side comparison of 2-4 products of the SAME category (docs/plans/
related-and-compare-tools.md). Used by the agent's compare_products tool and by
GET /api/products/compare (the UI table): the same function for both (AGENTS.md rule 1).

Within a category every product has the same spec attributes, so rows align perfectly.
"""

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.domain.catalog import ProductDetail, ProductStatus, get_product_detail
from app.domain.errors import DomainError

MIN_PRODUCTS = 2
MAX_PRODUCTS = 4
MISSING = "—"  # the product does not have that attribute (N/D is kept as "N/D")


class ComparedProduct(BaseModel):
    product_id: str
    name: str
    sku: str
    brand: str | None
    subcategory: str
    currency: str | None
    current_price: Decimal | None
    image_url: str | None


class ComparisonRow(BaseModel):
    group: str  # "General" for the fixed rows, else the spec group (Audio, Battery...)
    attribute: str
    values: list[str]  # one per product, same order as `products`
    differs: bool


class Comparison(BaseModel):
    category: str
    products: list[ComparedProduct]
    rows: list[ComparisonRow]


def _validate_ids(product_ids: list[str]) -> list[str]:
    ids = [pid.strip() for pid in product_ids]
    if len(set(ids)) != len(ids):
        raise DomainError("INVALID_INPUT", "Hay productos repetidos en la comparación")
    if not MIN_PRODUCTS <= len(ids) <= MAX_PRODUCTS:
        raise DomainError(
            "INVALID_INPUT",
            f"Se pueden comparar entre {MIN_PRODUCTS} y {MAX_PRODUCTS} productos",
            {"received": len(ids)},
        )
    return ids


def _fixed_rows(details: list[ProductDetail]) -> list[tuple[str, list[str]]]:
    def money(d: ProductDetail) -> str:
        return f"{d.currency} {d.current_price}"

    def rating(d: ProductDetail) -> str:
        return f"{d.rating} ({d.review_count} reviews)" if d.rating is not None else MISSING

    return [
        ("Price", [money(d) for d in details]),
        ("Discount", [f"{d.discount_percent}%" for d in details]),
        ("Rating", [rating(d) for d in details]),
        ("Stock", [str(d.available) for d in details]),
        (
            "Warranty",
            [f"{d.warranty_months} months" if d.warranty_months else MISSING for d in details],
        ),
        ("Return days", [str(d.return_days) if d.return_days else MISSING for d in details]),
    ]


def compare(session: Session, product_ids: list[str]) -> Comparison:
    """Raises INVALID_INPUT (count / repeated), NOT_FOUND, INACTIVE, MIXED_CATEGORIES."""
    ids = _validate_ids(product_ids)
    details = [get_product_detail(session, pid) for pid in ids]  # NOT_FOUND if missing

    inactive = [d.name for d in details if d.status == ProductStatus.DISCONTINUED]
    if inactive:
        raise DomainError(
            "INACTIVE",
            f"No se puede comparar un producto discontinuado: {', '.join(inactive)}",
            {"discontinued": inactive},
        )
    categories = {d.category for d in details}
    if len(categories) > 1:
        raise DomainError(
            "MIXED_CATEGORIES",
            "Solo se pueden comparar productos de la misma categoría",
            {"categories": {d.name: d.category for d in details}},
        )

    rows = [
        ComparisonRow(group="General", attribute=name, values=values, differs=len(set(values)) > 1)
        for name, values in _fixed_rows(details)
    ]
    # Spec rows: union of attributes, ordered by group then name
    by_product = [{s.name: s for s in d.specs} for d in details]
    attributes = sorted(
        {(s.group or "", s.name) for d in details for s in d.specs},
    )
    for group, name in attributes:
        values = [specs[name].value if name in specs else MISSING for specs in by_product]
        rows.append(
            ComparisonRow(
                group=group or "Other", attribute=name, values=values, differs=len(set(values)) > 1
            )
        )
    return Comparison(
        category=categories.pop(),
        products=[
            ComparedProduct(
                product_id=d.product_id,
                name=d.name,
                sku=d.sku,
                brand=d.brand,
                subcategory=d.subcategory,
                currency=d.currency,
                current_price=d.current_price,
                image_url=d.image_url,
            )
            for d in details
        ],
        rows=rows,
    )
