"""Public catalog endpoints (no login): listing, detail, cards, categories, brands,
warehouses.
Only HTTP here: the logic is in domain/catalog.py, the same one the agent tools use."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.domain import catalog
from app.domain.catalog import (
    BrandOut,
    CategoryOut,
    ProductDetail,
    ProductPage,
    ProductSort,
    ProductStatus,
    RelatedProduct,
    RelationType,
    WarehouseOut,
)
from app.domain.comparison import Comparison, compare
from app.domain.errors import DomainError
from app.retrieval.vocabulary import Category

router = APIRouter(tags=["catalog"])
Db = Annotated[Session, Depends(get_db)]


class ProductDetailOut(ProductDetail):
    alternatives: list[RelatedProduct] = []
    accessories: list[RelatedProduct] = []
    often_bought_with: list[RelatedProduct] = []


@router.get("/products", response_model=ProductPage)
def list_products(
    db: Db,
    category: Annotated[Category | None, Query(description="Dataset name, e.g. Headphones")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=catalog.MAX_PAGE_SIZE)] = 24,
    brand: Annotated[str | None, Query(description="Brand name, as in GET /api/brands")] = None,
    min_price: Annotated[Decimal | None, Query(description="Current price, USD")] = None,
    max_price: Annotated[Decimal | None, Query(description="Current price, USD")] = None,
    in_stock: Annotated[bool, Query(description="Only products with stock")] = False,
    sort: Annotated[ProductSort, Query(description="Order of the listing")] = ProductSort.DEFAULT,
    ids: Annotated[
        str | None, Query(description="Comma-separated IDs, for the chat cards (max 20)")
    ] = None,
):
    if ids is not None:
        filtered = (
            category
            or brand
            or min_price is not None
            or max_price is not None
            or in_stock
            or sort != ProductSort.DEFAULT
        )
        if filtered:
            raise DomainError("INVALID_INPUT", "Use either ids or the filters, not both")
        cards = catalog.product_cards(db, [i.strip() for i in ids.split(",") if i.strip()])
        return ProductPage(
            items=cards, page=1, page_size=len(cards), total=len(cards), total_pages=1
        )
    return catalog.list_products(
        db,
        category.value if category else None,
        page=page,
        page_size=page_size,
        brand=brand,
        min_price=min_price,
        max_price=max_price,
        in_stock=in_stock,
        sort=sort,
    )


@router.get("/products/compare", response_model=Comparison)
def compare_products(
    db: Db,
    ids: Annotated[str, Query(description="2 to 4 comma-separated IDs, same category")],
):
    """The comparison table (same function as the agent's compare_products tool)."""
    return compare(db, [i for i in ids.split(",") if i.strip()])


@router.get("/products/{product_id}", response_model=ProductDetailOut)
def product_detail(product_id: str, db: Db):
    detail = catalog.get_product_detail(db, product_id)
    alternatives = catalog.get_related(db, product_id, RelationType.ALTERNATIVE_TO).items
    if detail.status == ProductStatus.DISCONTINUED:
        # Not for sale: only alternatives, so the page can offer something else
        return ProductDetailOut(**detail.model_dump(), alternatives=alternatives)
    return ProductDetailOut(
        **detail.model_dump(),
        alternatives=alternatives,
        accessories=catalog.get_related(db, product_id, RelationType.ACCESSORY_FOR).items,
        often_bought_with=catalog.get_related(db, product_id, RelationType.OFTEN_BOUGHT_WITH).items,
    )


@router.get("/categories", response_model=list[CategoryOut])
def categories(db: Db):
    return catalog.list_categories(db)


@router.get("/brands", response_model=list[BrandOut])
def brands(
    db: Db,
    category: Annotated[Category | None, Query(description="Only brands in this category")] = None,
):
    return catalog.list_brands(db, category.value if category else None)


@router.get("/warehouses", response_model=list[WarehouseOut])
def warehouses(db: Db):
    return catalog.list_warehouses(db)
