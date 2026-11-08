"""Vector index of the catalog (docs/PLAN.md §9.4). One embedding per product."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Fixed by migration 0002. EMBEDDING_DIM must match; a different size needs a new migration.
EMBEDDING_COLUMN_DIM = 1536


class ProductEmbedding(Base):
    __tablename__ = "product_embeddings"

    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), primary_key=True)
    # Exact text that was embedded (useful to debug results and for the report)
    content: Mapped[str] = mapped_column(Text)
    # sha256(model + content): re-embed only when the text or the model changes
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_COLUMN_DIM))
    model: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
