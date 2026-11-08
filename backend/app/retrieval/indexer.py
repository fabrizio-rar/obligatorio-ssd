"""Index the catalog: build one document per product, embed only what changed,
upsert into product_embeddings (docs/PLAN.md §8 step 5, §9.4)."""

import hashlib
from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Brand, Category, Product, ProductEmbedding, ProductSpec, Subcategory
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.document_builder import ProductText, SpecText, build_document
from app.retrieval.embeddings import Embedder, EmbeddingError


class IndexReport(BaseModel):
    model: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    products: int = 0
    embedded: int = 0
    unchanged: int = 0
    tokens: int = 0
    estimated_cost_usd: float = 0.0

    def summary(self) -> str:
        return (
            f"Embeddings ({self.model}): {self.products} products, "
            f"{self.embedded} embedded, {self.unchanged} unchanged, "
            f"{self.tokens} tokens (~USD {self.estimated_cost_usd:.4f})"
        )


def content_hash(model: str, content: str) -> str:
    """Changes when the text OR the model changes (vectors of different models don't mix)."""
    return hashlib.sha256(f"{model}\n{content}".encode()).hexdigest()


def load_product_texts(session: Session) -> list[ProductText]:
    """Every product, active or not: inactive ones are indexed and filtered in SQL (§9.2)."""
    specs: dict[str, list[SpecText]] = defaultdict(list)
    for spec in session.scalars(select(ProductSpec)):
        specs[spec.product_id].append(
            SpecText(
                group=spec.attribute_group,
                name=spec.attribute_name,
                value_text=spec.value_text,
                value_number=spec.value_number,
                unit=spec.unit,
            )
        )

    rows = session.execute(
        select(Product, Brand, Subcategory, Category)
        .join(Brand, Brand.id == Product.brand_id)
        .join(Subcategory, Subcategory.id == Product.subcategory_id)
        .join(Category, Category.id == Subcategory.category_id)
        .order_by(Product.id)
    )
    return [
        ProductText(
            product_id=product.id,
            name=product.name,
            brand=brand.name,
            brand_positioning=brand.positioning,
            category=category.name,
            subcategory=subcategory.name,
            short_description=product.short_description,
            description=product.description,
            key_features=product.key_features,
            recommended_for=product.recommended_for,
            not_recommended_for=product.not_recommended_for,
            specs=specs[product.id],
            tags=product.tags,
        )
        for product, brand, subcategory, category in rows
    ]


def _batches[T](items: list[T], size: int) -> Iterator[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def index_products(
    session: Session,
    embedder: Embedder,
    force: bool = False,
    usd_per_1m_tokens: float = 0.0,
    batch_size: int = 100,
) -> IndexReport:
    """Embed new or changed products. Commits after every batch, so if the API fails
    halfway the batches already done are kept and the next run only does the rest."""
    if embedder.dim != EMBEDDING_COLUMN_DIM:
        raise EmbeddingError(
            "DIM_MISMATCH",
            f"EMBEDDING_DIM={embedder.dim} but the DB column is VECTOR({EMBEDDING_COLUMN_DIM}). "
            "Changing the dimension needs a new migration.",
            retryable=False,
        )

    report = IndexReport(model=embedder.model)
    documents = {p.product_id: build_document(p) for p in load_product_texts(session)}
    hashes = {pid: content_hash(embedder.model, text) for pid, text in documents.items()}
    stored = dict(
        session.execute(select(ProductEmbedding.product_id, ProductEmbedding.content_hash)).all()
    )
    session.commit()  # end the read transaction before the (slow) API calls

    pending = [pid for pid in documents if force or stored.get(pid) != hashes[pid]]
    report.products = len(documents)
    report.unchanged = len(documents) - len(pending)

    for batch in _batches(pending, batch_size):
        result = embedder.embed_documents([documents[pid] for pid in batch])
        rows = [
            {
                "product_id": pid,
                "content": documents[pid],
                "content_hash": hashes[pid],
                "embedding": vector,
                "model": embedder.model,
            }
            for pid, vector in zip(batch, result.vectors, strict=True)
        ]
        stmt = insert(ProductEmbedding).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["product_id"],
            set_={
                "content": stmt.excluded.content,
                "content_hash": stmt.excluded.content_hash,
                "embedding": stmt.excluded.embedding,
                "model": stmt.excluded.model,
                "updated_at": func.now(),
            },
        )
        session.execute(stmt)
        session.commit()
        report.embedded += len(batch)
        report.tokens += result.tokens

    report.estimated_cost_usd = report.tokens / 1_000_000 * usd_per_1m_tokens
    return report


def nearest_products(
    session: Session, embedder: Embedder, query: str, limit: int = 5
) -> list[tuple[str, str, bool, float]]:
    """Debug helper (not the real search, that is N8): (id, name, active, cosine distance)."""
    vector = embedder.embed_query(query)
    distance = ProductEmbedding.embedding.cosine_distance(vector)
    rows = session.execute(
        select(Product.id, Product.name, Product.active, distance)
        .join(ProductEmbedding, ProductEmbedding.product_id == Product.id)
        .order_by(distance)
        .limit(limit)
    )
    return [(pid, name, active, float(dist)) for pid, name, active, dist in rows]
