"""Product search used by the agent's search_products tool (docs/PLAN.md §9.5).

    1. Hard filters in SQL: active, category, subcategory, brand, price, avoid-cases, stock.
    2. Semantic ranking: cosine distance between the query and product_embeddings.
    3. Use-case ranking: candidates that match the requested use cases. It is a ranking
       signal, NOT a filter: a badly chosen use case worsens the order, never empties it.
    4. RRF fusion of both rankings, ties broken by rating and then review count.

Price and stock always come from the DB, never from the embedded text.
"""

import logging
from collections.abc import Sequence
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.errors import DomainError
from app.domain.inventory import StockStatus, stock_status
from app.models import Brand, Price, Product, ProductEmbedding, Subcategory
from app.models import Category as CategoryModel
from app.models.catalog import product_availability
from app.retrieval.embeddings import Embedder, EmbeddingError
from app.retrieval.vocabulary import AvoidCase, Category, UseCase, subcategory_belongs

logger = logging.getLogger(__name__)

RRF_K = 60  # standard RRF constant: dampens the weight of the top positions
SEMANTIC_TOP_K = 20  # only the 20 nearest candidates get a semantic score


class SearchQuery(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)  # "   " fails min_length

    query: str = Field(min_length=1, max_length=500, description="What the user needs, in English")
    category: Category | None = None
    subcategory: str | None = None
    brand: str | None = None
    min_price: Decimal | None = Field(default=None, ge=0)
    max_price: Decimal | None = Field(default=None, ge=0)
    use_cases: list[UseCase] = Field(default_factory=list, max_length=5)
    exclude_use_cases: list[AvoidCase] = Field(default_factory=list, max_length=5)
    in_stock_only: bool = True
    limit: int = Field(default=5, ge=1, le=10)

    @field_validator("subcategory", "brand")
    @classmethod
    def empty_is_none(cls, value: str | None) -> str | None:
        return value or None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        both_prices = self.min_price is not None and self.max_price is not None
        if both_prices and self.min_price > self.max_price:
            raise ValueError("min_price cannot be greater than max_price")
        if self.subcategory is not None:
            if self.category is None:
                raise ValueError("subcategory requires category (names repeat across categories)")
            if not subcategory_belongs(self.category, self.subcategory):
                raise ValueError(f"'{self.subcategory}' is not a subcategory of {self.category}")
        return self


class SearchHit(BaseModel):
    product_id: str
    sku: str
    name: str
    brand: str
    category: str
    subcategory: str
    current_price: Decimal
    list_price: Decimal
    discount_percent: int
    currency: str
    available: int
    stock_status: StockStatus
    rating: Decimal | None
    review_count: int | None
    matched_use_cases: list[str]


class SearchResult(BaseModel):
    ok: bool = True
    hits: list[SearchHit]
    total_candidates: int  # products that passed the hard filters
    semantic_used: bool  # False if the query could not be embedded (fallback ranking)


def rrf(rankings: Sequence[Sequence[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + position)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, product_id in enumerate(ranking, start=1):
            scores[product_id] = scores.get(product_id, 0.0) + 1.0 / (k + position)
    return scores


def _resolve_brand(session: Session, brand: str) -> str:
    """Case-insensitive exact match against the brands table."""
    brand_id = session.scalar(select(Brand.id).where(func.lower(Brand.name) == brand.lower()))
    if brand_id is None:
        valid = sorted(session.scalars(select(Brand.name)))
        raise DomainError("UNKNOWN_BRAND", f"Unknown brand '{brand}'", {"valid_brands": valid})
    return brand_id


def search(session: Session, q: SearchQuery, embedder: Embedder | None) -> SearchResult:
    distance = None
    semantic_used = False
    if embedder is not None:
        try:
            vector = embedder.embed_query(q.query)
            distance = ProductEmbedding.embedding.cosine_distance(vector).label("distance")
            semantic_used = True
        except EmbeddingError as error:
            # Fallback: rank by use cases and rating only. The turn goes on.
            logger.warning("Query embedding failed [%s]: %s", error.code, error.message)

    # 1. Hard filters
    columns = [Product.id, Product.recommended_for, Product.rating, Product.review_count]
    stmt = (
        select(*columns, *([distance] if distance is not None else []))
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(CategoryModel, CategoryModel.id == Subcategory.category_id)
        .join(Price, Price.product_id == Product.id)
        .join(product_availability, product_availability.c.product_id == Product.id)
        .where(Product.active.is_(True))
    )
    if distance is not None:
        # Outer join: a product not indexed yet is not hidden, it just ranks last
        stmt = stmt.outerjoin(ProductEmbedding, ProductEmbedding.product_id == Product.id)
    if q.category is not None:
        stmt = stmt.where(CategoryModel.name == q.category.value)
    if q.subcategory is not None:
        stmt = stmt.where(Subcategory.name == q.subcategory)
    if q.brand is not None:
        stmt = stmt.where(Product.brand_id == _resolve_brand(session, q.brand))
    if q.min_price is not None:
        stmt = stmt.where(Price.current_price >= q.min_price)
    if q.max_price is not None:
        stmt = stmt.where(Price.current_price <= q.max_price)
    if q.exclude_use_cases:
        avoid = [a.value for a in q.exclude_use_cases]
        stmt = stmt.where(~Product.not_recommended_for.overlap(avoid))
    if q.in_stock_only:
        stmt = stmt.where(product_availability.c.available > 0)

    candidates = session.execute(stmt).all()
    wanted = {u.value for u in q.use_cases}
    popularity = {c.id: (c.rating or 0, c.review_count or 0) for c in candidates}
    matched = {c.id: sorted(wanted.intersection(c.recommended_for)) for c in candidates}

    # 2-3. Rankings
    rankings: list[list[str]] = []
    if semantic_used:
        by_distance = sorted(
            (c for c in candidates if c.distance is not None), key=lambda c: (c.distance, c.id)
        )
        rankings.append([c.id for c in by_distance[:SEMANTIC_TOP_K]])
    if wanted:
        with_uses = [c for c in candidates if matched[c.id]]
        with_uses.sort(key=lambda c: (-len(matched[c.id]), *(-v for v in popularity[c.id]), c.id))
        rankings.append([c.id for c in with_uses])
    if not rankings:
        # No embedding and no use cases: best rated first
        by_rating = sorted(candidates, key=lambda c: (*(-v for v in popularity[c.id]), c.id))
        rankings.append([c.id for c in by_rating])

    # 4. Fusion + tie-breakers. Candidates outside every ranking (e.g. not indexed yet)
    # are not hidden: they go last, best rated first.
    scores = rrf(rankings)
    ordered = sorted(
        popularity, key=lambda pid: (-scores.get(pid, 0.0), *(-v for v in popularity[pid]), pid)
    )
    top = ordered[: q.limit]

    return SearchResult(
        hits=_load_hits(session, top, matched),
        total_candidates=len(candidates),
        semantic_used=semantic_used,
    )


def _load_hits(
    session: Session, product_ids: list[str], matched: dict[str, list[str]]
) -> list[SearchHit]:
    """Fresh price and stock from the DB for the final results, in ranking order."""
    if not product_ids:
        return []
    rows = session.execute(
        select(Product, Brand.name, CategoryModel.name, Subcategory.name, Price)
        .add_columns(product_availability.c.available)
        .join(Brand, Brand.id == Product.brand_id)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(CategoryModel, CategoryModel.id == Subcategory.category_id)
        .join(Price, Price.product_id == Product.id)
        .join(product_availability, product_availability.c.product_id == Product.id)
        .where(Product.id.in_(product_ids))
    )
    by_id = {}
    for product, brand, category, subcategory, price, available in rows:
        by_id[product.id] = SearchHit(
            product_id=product.id,
            sku=product.sku,
            name=product.name,
            brand=brand,
            category=category,
            subcategory=subcategory,
            current_price=price.current_price,
            list_price=price.list_price,
            discount_percent=price.discount_percent,
            currency=price.currency,
            available=available,
            stock_status=stock_status(available),
            rating=product.rating,
            review_count=product.review_count,
            matched_use_cases=matched.get(product.id, []),
        )
    return [by_id[pid] for pid in product_ids]
