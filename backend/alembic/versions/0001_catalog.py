"""Catalog tables loaded from the Excel dataset + product_availability view.

Revision ID: 0001_catalog
Revises:
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_catalog"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEARCH_TSV_EXPR = (
    "setweight(to_tsvector('english', coalesce(name, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(short_description, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(description, '')), 'C')"
)

# Same rule as app.domain.inventory.stock_status, applied to the total across warehouses
PRODUCT_AVAILABILITY_VIEW = """
CREATE VIEW product_availability AS
SELECT
    product_id,
    SUM(available_qty)::int AS available,
    CASE
        WHEN SUM(available_qty) <= 0 THEN 'Out of stock'
        WHEN SUM(available_qty) <= 2 THEN 'Low stock'
        ELSE 'In stock'
    END AS status
FROM inventory
GROUP BY product_id
"""


def upgrade() -> None:
    # Needed later for product_embeddings (N8); enabled now so the DB is ready.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "brands",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("country_of_origin", sa.Text),
        sa.Column("positioning", sa.Text),
    )
    op.create_table(
        "categories",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("department", sa.Text),
    )
    op.create_table(
        "subcategories",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("category_id", sa.String(16), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("sort_order", sa.Integer, nullable=False),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("sku", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("brand_id", sa.String(16), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column(
            "subcategory_id", sa.String(16), sa.ForeignKey("subcategories.id"), nullable=False
        ),
        sa.Column("short_description", sa.Text),
        sa.Column("description", sa.Text),
        sa.Column("recommended_for", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("not_recommended_for", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("key_features", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text), nullable=False),
        sa.Column("color", sa.Text),
        sa.Column("weight_kg", sa.Numeric(8, 2)),
        sa.Column("width_cm", sa.Numeric(8, 2)),
        sa.Column("height_cm", sa.Numeric(8, 2)),
        sa.Column("depth_cm", sa.Numeric(8, 2)),
        sa.Column("warranty_months", sa.Integer),
        sa.Column("return_days", sa.Integer),
        sa.Column("rating", sa.Numeric(2, 1)),
        sa.Column("review_count", sa.Integer),
        sa.Column("launch_date", sa.Date),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("image_url", sa.Text),
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR,
            sa.Computed(SEARCH_TSV_EXPR, persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_products_recommended_for", "products", ["recommended_for"], postgresql_using="gin"
    )
    op.create_index("ix_products_search_tsv", "products", ["search_tsv"], postgresql_using="gin")
    op.create_index("ix_products_subcategory_id", "products", ["subcategory_id"])
    op.create_index("ix_products_brand_id", "products", ["brand_id"])

    op.create_table(
        "prices",
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("list_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("current_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("discount_percent", sa.Integer, nullable=False),
        sa.Column("tax_included", sa.Boolean, nullable=False),
        sa.Column("updated_at", sa.DateTime),
        sa.CheckConstraint("list_price > 0 AND current_price > 0", name="ck_prices_positive"),
        sa.CheckConstraint("discount_percent BETWEEN 0 AND 100", name="ck_prices_discount_range"),
    )
    op.create_table(
        "product_specs",
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("attribute_name", sa.Text, primary_key=True),
        sa.Column("attribute_group", sa.Text),
        sa.Column("value_text", sa.Text),
        sa.Column("value_number", sa.Numeric(12, 3)),
        sa.Column("unit", sa.Text),
    )
    op.create_table(
        "warehouses",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("city", sa.Text),
        sa.Column("department", sa.Text),
        sa.Column("country", sa.Text),
        sa.Column("pickup_enabled", sa.Boolean, nullable=False),
        sa.Column("shipping_enabled", sa.Boolean, nullable=False),
    )
    op.create_table(
        "inventory",
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("warehouse_id", sa.String(16), sa.ForeignKey("warehouses.id"), primary_key=True),
        sa.Column("on_hand_qty", sa.Integer, nullable=False),
        sa.Column("reserved_qty", sa.Integer, nullable=False),
        sa.Column(
            "available_qty",
            sa.Integer,
            sa.Computed("on_hand_qty - reserved_qty", persisted=True),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime),
        sa.CheckConstraint(
            "on_hand_qty >= reserved_qty AND reserved_qty >= 0", name="ck_inventory_quantities"
        ),
    )
    op.create_table(
        "product_relations",
        sa.Column("product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column(
            "related_product_id", sa.String(32), sa.ForeignKey("products.id"), primary_key=True
        ),
        sa.Column("relation_type", sa.String(32), primary_key=True),
        sa.Column("strength", sa.Numeric(4, 3)),
        sa.CheckConstraint("product_id <> related_product_id", name="ck_relations_no_self"),
        sa.CheckConstraint(
            "relation_type IN ('alternative_to', 'accessory_for', 'often_bought_with')",
            name="ck_relations_type",
        ),
    )

    op.execute(PRODUCT_AVAILABILITY_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS product_availability")
    for table in (
        "product_relations",
        "inventory",
        "warehouses",
        "product_specs",
        "prices",
        "products",
        "subcategories",
        "categories",
        "brands",
    ):
        op.drop_table(table)
