"""SQLAlchemy models. Importing this package registers every table in Base.metadata."""

from app.models.catalog import (
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

__all__ = [
    "Brand",
    "Category",
    "Inventory",
    "Price",
    "Product",
    "ProductRelation",
    "ProductSpec",
    "Subcategory",
    "Warehouse",
]
