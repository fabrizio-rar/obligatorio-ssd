from decimal import Decimal

from app.domain.catalog import EMPTY_SPEC_VALUE
from app.retrieval.document_builder import ProductText, SpecText, build_document, format_spec


def _product(**overrides) -> ProductText:
    data = {
        "product_id": "MN-HDP-0691",
        "name": "Nimbus Sound 691",
        "brand": "Nimbus",
        "brand_positioning": "mobility",
        "category": "Headphones",
        "subcategory": "On-Ear",
        "short_description": "Over-Ear headphones with ANC.",
        "description": "Designed for music, calls, commuting.",
        "key_features": ["ANC", "22 h battery"],
        "recommended_for": ["music", "calls"],
        "not_recommended_for": [],
        "specs": [
            SpecText("Battery", "Battery Life", None, Decimal("22.000"), "h"),
            SpecText("Audio", "Active Noise Cancellation", "Yes", None, None),
        ],
        "tags": ["audio", "headphones"],
    }
    data.update(overrides)
    return ProductText(**data)


def test_document_follows_the_template():
    assert build_document(_product()) == (
        "Product: Nimbus Sound 691\n"
        "Brand: Nimbus (mobility)\n"
        "Category: Headphones > On-Ear\n"
        "Summary: Over-Ear headphones with ANC.\n"
        "Description: Designed for music, calls, commuting.\n"
        "Key features: ANC; 22 h battery\n"
        "Recommended for: music; calls\n"
        "Specs: Active Noise Cancellation: Yes; Battery Life: 22 h\n"
        "Tags: audio; headphones"
    )


def test_empty_fields_are_left_out():
    doc = build_document(_product(not_recommended_for=[], description=None, tags=[]))
    assert "Not recommended for" not in doc
    assert "Description" not in doc
    assert "Tags" not in doc


def test_not_recommended_for_is_included_when_present():
    doc = build_document(_product(not_recommended_for=["air travel"]))
    assert "Not recommended for: air travel" in doc


def test_document_is_deterministic_regardless_of_spec_order():
    product = _product()
    shuffled = _product(specs=list(reversed(product.specs)))
    assert build_document(product) == build_document(shuffled)


def test_empty_specs_are_skipped():
    spec = SpecText("Build", "Water Resistance", EMPTY_SPEC_VALUE, None, None)
    assert format_spec(spec) is None
    doc = build_document(_product(specs=[spec]))
    assert "Water Resistance" not in doc
    assert "Specs" not in doc


def test_numbers_are_formatted_without_trailing_zeros():
    assert format_spec(SpecText(None, "Weight", None, Decimal("0.500"), "kg")) == "Weight: 0.5 kg"
    assert format_spec(SpecText(None, "Ports", None, Decimal("4.000"), None)) == "Ports: 4"


def test_document_never_contains_price_stock_or_rating():
    # ProductText has no such fields: the document cannot leak dynamic data
    fields = set(ProductText.__dataclass_fields__)
    assert not fields & {"price", "current_price", "list_price", "stock", "rating", "available"}
    doc = build_document(_product()).lower()
    assert "price" not in doc and "stock" not in doc and "rating" not in doc
