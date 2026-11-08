"""product_embeddings: one vector per product, HNSW cosine index.

Revision ID: 0002_product_embeddings
Revises: 0001_catalog
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision: str = "0002_product_embeddings"
down_revision: str | None = "0001_catalog"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# text-embedding-3-small. Changing EMBEDDING_DIM requires a new migration.
EMBEDDING_DIM = 1536


def upgrade() -> None:
    op.create_table(
        "product_embeddings",
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), nullable=False),
    )
    # With 360 rows an exact scan is enough; the index is there to show the pattern (§9.4)
    op.create_index(
        "ix_product_embeddings_hnsw",
        "product_embeddings",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_table("product_embeddings")
