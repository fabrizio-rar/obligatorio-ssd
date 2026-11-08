"""get_related() / compare() in the domain, GET /api/products/compare, and the two agent
tools (with FakeLLM). Real dataset."""

import asyncio
import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agent.llm.fake import FakeLLM, final, tool_call
from app.agent.loop import TurnLimits, run_turn
from app.agent.state import AgentState
from app.agent.tools import ToolContext
from app.auth import service as auth
from app.domain.catalog import RelationType, get_related
from app.domain.comparison import MISSING, compare
from app.domain.errors import DomainError
from app.models import Product, ProductSpec
from app.models.retrieval import EMBEDDING_COLUMN_DIM
from app.retrieval.embeddings import FakeEmbedder

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db(catalog_db) -> Session:
    return catalog_db


def _id(db, name):
    return db.scalar(select(Product.id).where(Product.name == name))


# --- Related (domain) ----------------------------------------------------------------------------


def test_alternatives_are_ordered_and_filtered(db):
    nimbus = _id(db, "Nimbus Sound 691")  # out of stock
    result = get_related(db, nimbus, RelationType.ALTERNATIVE_TO)
    assert result.items
    assert all(i.available > 0 for i in result.items)
    strengths = [i.strength for i in result.items]
    assert strengths == sorted(strengths, reverse=True)
    assert result.items[0].name == "Quanta Quiet 27"  # strength 0.93 in the dataset


def test_filtered_out_counts_inactive_targets(db):
    source = db.scalar(
        text(
            "SELECT r.product_id FROM product_relations r JOIN products p "
            "ON p.id = r.related_product_id WHERE NOT p.active "
            "AND r.relation_type = 'alternative_to' LIMIT 1"
        )
    )
    result = get_related(db, source, RelationType.ALTERNATIVE_TO, in_stock_only=False)
    assert result.filtered_out["inactive"] >= 1
    assert all(i.product_id != source for i in result.items)


def test_discontinued_source_still_has_alternatives(db):
    result = get_related(db, _id(db, "Cedar Air 243"), RelationType.ALTERNATIVE_TO)
    assert all(i.category == "Headphones" for i in result.items)


def test_related_of_unknown_product(db):
    with pytest.raises(DomainError) as info:
        get_related(db, "MN-XXX-0000", RelationType.ACCESSORY_FOR)
    assert info.value.code == "NOT_FOUND"


# --- Compare (domain + API) ----------------------------------------------------------------------


def test_compare_two_headphones_aligns_every_row(db):
    a, b = _id(db, "Orbit Sound 458"), _id(db, "Quanta Quiet 638")
    comparison = compare(db, [a, b])

    assert comparison.category == "Headphones"
    assert [p.product_id for p in comparison.products] == [a, b]
    fixed = [r for r in comparison.rows if r.group == "General"]
    specs = [r for r in comparison.rows if r.group != "General"]
    assert [r.attribute for r in fixed] == [
        "Price",
        "Discount",
        "Rating",
        "Stock",
        "Warranty",
        "Return days",
    ]
    assert len(specs) == 9  # every headphone has the same 9 attributes
    assert all(len(r.values) == 2 for r in comparison.rows)
    for row in comparison.rows:
        assert row.differs == (row.values[0] != row.values[1])
    anc = next(r for r in specs if r.attribute == "Active Noise Cancellation")
    db_values = [
        db.scalar(
            select(ProductSpec.value_text).where(
                ProductSpec.product_id == pid,
                ProductSpec.attribute_name == "Active Noise Cancellation",
            )
        )
        for pid in (a, b)
    ]
    assert anc.values == db_values


def test_compare_products_with_the_same_name(db):
    ids = db.scalars(select(Product.id).where(Product.name == "Kairo Drive Pro 2TB")).all()
    comparison = compare(db, list(ids))
    assert len(comparison.products) == 2
    assert len({p.sku for p in comparison.products}) == 2  # two different columns


def test_nd_is_not_no(db):
    row = db.execute(
        text(
            "SELECT ps.product_id, ps.attribute_name, s.category_id FROM product_specs ps "
            "JOIN products p ON p.id = ps.product_id "
            "JOIN subcategories s ON s.id = p.subcategory_id "
            "WHERE ps.value_text = 'N/D' AND p.active LIMIT 1"
        )
    ).first()
    other = db.scalar(
        text(
            "SELECT p.id FROM products p JOIN subcategories s ON s.id = p.subcategory_id "
            "WHERE s.category_id = :cat AND p.active AND p.id <> :pid LIMIT 1"
        ),
        {"cat": row.category_id, "pid": row.product_id},
    )
    comparison = compare(db, [row.product_id, other])
    attribute = next(r for r in comparison.rows if r.attribute == row.attribute_name)
    assert attribute.values[0] == "N/D" and attribute.values[0] != "No"
    assert MISSING not in attribute.values  # same category: the attribute exists for both


@pytest.mark.parametrize(
    ("names", "code"),
    [
        (["Orbit Sound 458"], "INVALID_INPUT"),
        (["Orbit Sound 458", "Orbit Sound 458"], "INVALID_INPUT"),
        (
            [
                "Orbit Sound 458",
                "Vector Air 690",
                "Quanta Quiet 638",
                "Helix Sound 41",
                "Orbit Sound 386",
            ],
            "INVALID_INPUT",
        ),
        (["Orbit Sound 458", "Cedar Air 243"], "INACTIVE"),
        (["Orbit Sound 458", "Flux Edge 15 8/256"], "MIXED_CATEGORIES"),
    ],
)
def test_compare_errors(db, names, code):
    with pytest.raises(DomainError) as info:
        compare(db, [_id(db, n) for n in names])
    assert info.value.code == code


def test_compare_unknown_id(db):
    with pytest.raises(DomainError) as info:
        compare(db, [_id(db, "Orbit Sound 458"), "MN-XXX-0000"])
    assert info.value.code == "NOT_FOUND"


def test_compare_endpoint(api, catalog_db):
    a, b = _id(catalog_db, "Orbit Sound 458"), _id(catalog_db, "Quanta Quiet 638")
    body = api.get("/api/products/compare", params={"ids": f"{a},{b}"}).json()
    assert [p["product_id"] for p in body["products"]] == [a, b]
    assert len(body["rows"]) == 15
    mixed = api.get(
        "/api/products/compare", params={"ids": f"{a},{_id(catalog_db, 'Flux Edge 15 8/256')}"}
    )
    assert mixed.status_code == 422
    assert mixed.json()["error"]["code"] == "MIXED_CATEGORIES"
    assert api.get("/api/products/compare").status_code == 422  # ids is required


# --- Agent tools ---------------------------------------------------------------------------------

EMBEDDER = FakeEmbedder(dim=EMBEDDING_COLUMN_DIM)


def _answer(type_, product_ids=()):
    return {
        "type": type_,
        "message": "ok",
        "product_ids": list(product_ids),
        "clarifying_question": None,
        "suggested_replies": [],
    }


def _run(db, steps):
    user = auth.register(db, f"rc{len(steps)}{id(steps) % 100000}", "secret123")
    ctx = ToolContext(db, EMBEDDER, user_id=user.id)
    limits = TurnLimits(max_steps=6, timeout_seconds=30, max_tokens=100_000)
    return asyncio.run(run_turn(FakeLLM(steps), ctx, limits, [], "...", AgentState()))


def test_out_of_stock_then_curated_alternatives(db):
    nimbus = _id(db, "Nimbus Sound 691")

    def recommend(request):
        products = json.loads(request["tool_outputs"][0].output)["products"]
        return final(_answer("recommendation", [p["product_id"] for p in products]))

    turn = _run(
        db,
        [
            tool_call("get_product", {"name": "Nimbus Sound 691", "product_id": None}),
            tool_call(
                "get_related_products",
                {"product_id": nimbus, "relation_type": "alternative_to", "in_stock_only": True},
                call_id="c2",
            ),
            recommend,
        ],
    )
    related = turn.tool_executions[1][1]
    assert related.result["products"][0]["name"] == "Quanta Quiet 27"
    assert "filtered_out" in related.result
    assert turn.response.product_ids == related.product_ids  # allowed: came from a tool
    assert turn.response.comparison_ids == []


def test_compare_fills_comparison_ids_from_the_tool(db):
    a, b = _id(db, "Orbit Sound 458"), _id(db, "Quanta Quiet 638")
    turn = _run(
        db,
        [tool_call("compare_products", {"product_ids": [a, b]}), final(_answer("comparison"))],
    )
    result = turn.tool_executions[0][1].result
    assert result["rows"][0]["differs"] is True  # differing rows come first
    assert all(len(r["values"]) == 2 for r in result["rows"])
    assert turn.response.type == "comparison"
    assert turn.response.comparison_ids == [a, b]  # filled by the backend


def test_compare_errors_go_back_to_the_model(db):
    a, laptop = _id(db, "Orbit Sound 458"), _id(db, "Flux Edge 15 8/256")
    one = _run(db, [tool_call("compare_products", {"product_ids": [a]}), final(_answer("info"))])
    assert one.tool_executions[0][1].result["error"]["code"] == "INVALID_ARGUMENTS"  # schema
    mixed = _run(
        db,
        [tool_call("compare_products", {"product_ids": [a, laptop]}), final(_answer("info"))],
    )
    assert mixed.tool_executions[0][1].result["error"]["code"] == "MIXED_CATEGORIES"
    assert mixed.response.comparison_ids == []
