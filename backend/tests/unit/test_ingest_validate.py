from decimal import Decimal

from app.ingest.report import IngestReport
from app.ingest.validate import EMPTY_SPEC_VALUE, validate_catalog
from tests.factories import EXPECTED_LAUNCH_DATE, make_records


def _validate(records):
    report = IngestReport(dataset="test")
    return validate_catalog(records, report), report


def _rejected(report, sheet):
    return [issue for issue in report.rejected if issue.sheet == sheet]


def test_valid_workbook_loads_everything():
    data, report = _validate(make_records())

    assert report.rejected == []
    assert len(data.brands) == 2
    assert len(data.categories) == 2
    assert len(data.subcategories) == 2
    assert len(data.products) == 2
    assert len(data.prices) == 2
    assert len(data.product_specs) == 3
    assert len(data.inventory) == 4
    assert len(data.product_relations) == 1
    assert report.sheets["Inventory"].read == report.sheets["Inventory"].valid == 4


def test_product_fields_are_normalized():
    data, _ = _validate(make_records())
    product = next(p for p in data.products if p["id"] == "MN-HDP-0001")

    assert product["recommended_for"] == ["calls", "video calls"]
    assert product["not_recommended_for"] == []
    assert product["launch_date"] == EXPECTED_LAUNCH_DATE
    assert product["rating"] == Decimal("4.3")
    assert "category" not in product and "brand" not in product


def test_subcategory_is_resolved_by_category_and_name():
    # Both categories have a subcategory called "Wireless"
    data, _ = _validate(make_records())
    by_id = {p["id"]: p["subcategory_id"] for p in data.products}
    assert by_id == {"MN-HDP-0001": "SUB001", "MN-MOU-0001": "SUB002"}


def test_unknown_subcategory_is_rejected():
    records = make_records()
    records["Products"][0]["subcategory"] = "Bone conduction"
    data, report = _validate(records)

    assert [p["id"] for p in data.products] == ["MN-MOU-0001"]
    assert "unknown category/subcategory" in _rejected(report, "Products")[0].message


def test_rejected_product_takes_its_dependents_with_it():
    records = make_records()
    records["Products"][0]["brand_id"] = "BR999"
    data, report = _validate(records)

    assert {p["id"] for p in data.products} == {"MN-MOU-0001"}
    assert {p["product_id"] for p in data.prices} == {"MN-MOU-0001"}
    assert {s["product_id"] for s in data.product_specs} == {"MN-MOU-0001"}
    assert {i["product_id"] for i in data.inventory} == {"MN-MOU-0001"}
    assert data.product_relations == []
    assert "unknown brand_id BR999" in _rejected(report, "Products")[0].message
    assert len(_rejected(report, "Inventory")) == 2
    assert len(_rejected(report, "Relations")) == 1


def test_duplicate_product_id_and_sku_are_rejected():
    records = make_records()
    dup_id = dict(records["Products"][0], sku="OTHER")
    dup_sku = dict(records["Products"][0], product_id="MN-HDP-0002")
    records["Products"] += [dup_id, dup_sku]
    data, report = _validate(records)

    assert len(data.products) == 2
    messages = [i.message for i in _rejected(report, "Products")]
    assert any("duplicate key MN-HDP-0001" in m for m in messages)
    assert any("duplicate sku HDP-1" in m for m in messages)
    # Excel row numbers: header is row 1, so the 3rd and 4th records are rows 4 and 5
    assert [i.row for i in _rejected(report, "Products")] == [4, 5]


def test_invalid_row_does_not_abort_the_rest():
    records = make_records()
    records["Products"][1]["rating"] = 7  # out of range
    data, report = _validate(records)

    assert [p["id"] for p in data.products] == ["MN-HDP-0001"]
    assert "rating" in _rejected(report, "Products")[0].message


def test_inconsistent_price_is_rejected():
    records = make_records()
    records["Pricing"][0]["current_price"] = 150.0  # 200 x 0.9 = 180
    data, report = _validate(records)

    assert [p["product_id"] for p in data.prices] == ["MN-MOU-0001"]
    assert "current_price" in _rejected(report, "Pricing")[0].message
    assert any("has no price" in w.message for w in report.warnings)


def test_price_rounding_within_a_cent_is_accepted():
    records = make_records()
    records["Pricing"][0].update(list_price=493.28, discount_percent=5, current_price=468.62)
    data, report = _validate(records)

    assert _rejected(report, "Pricing") == []
    assert data.prices[0]["current_price"] == Decimal("468.62")


def test_non_positive_price_is_rejected():
    records = make_records()
    records["Pricing"][1].update(list_price=0, current_price=0)
    _, report = _validate(records)
    assert len(_rejected(report, "Pricing")) == 1


def test_empty_spec_is_loaded_as_nd_with_warning():
    records = make_records()
    records["Specifications"][0]["value_text"] = None
    data, report = _validate(records)

    spec = next(s for s in data.product_specs if s["attribute_name"] == "ANC")
    assert spec["value_text"] == EMPTY_SPEC_VALUE
    assert spec["value_number"] is None
    assert report.findings["empty_specs"] == 1
    assert any("'ANC' has no value" in w.message for w in report.warnings)


def test_duplicate_spec_key_is_rejected():
    records = make_records()
    records["Specifications"].append(dict(records["Specifications"][0], value_text="No"))
    data, report = _validate(records)

    assert len(data.product_specs) == 3
    assert len(_rejected(report, "Specifications")) == 1


def test_inventory_available_must_match_on_hand_minus_reserved():
    records = make_records()
    records["Inventory"][0]["available_qty"] = 5  # 5 - 1 = 4
    data, report = _validate(records)

    assert len(data.inventory) == 3
    assert "available_qty" in _rejected(report, "Inventory")[0].message


def test_inventory_status_must_follow_the_rule():
    records = make_records()
    records["Inventory"][2]["inventory_status"] = "In stock"  # available 2 -> Low stock
    _, report = _validate(records)
    assert "inventory_status" in _rejected(report, "Inventory")[0].message


def test_inventory_reserved_over_on_hand_is_rejected():
    records = make_records()
    records["Inventory"][0].update(on_hand_qty=1, reserved_qty=2, available_qty=-1)
    _, report = _validate(records)
    assert len(_rejected(report, "Inventory")) == 1


def test_inventory_unknown_warehouse_is_rejected():
    records = make_records()
    records["Inventory"][0]["warehouse_id"] = "WH-ZZZ"
    _, report = _validate(records)
    assert "unknown warehouse WH-ZZZ" in _rejected(report, "Inventory")[0].message


def test_inventory_does_not_store_status_or_available():
    data, _ = _validate(make_records())
    assert "available_qty" not in data.inventory[0]
    assert "inventory_status" not in data.inventory[0]


def test_self_relation_and_unknown_type_are_rejected():
    records = make_records()
    records["Relations"] += [
        {
            "product_id": "MN-HDP-0001",
            "related_product_id": "MN-HDP-0001",
            "relation_type": "alternative_to",
            "strength": 0.9,
        },
        {
            "product_id": "MN-HDP-0001",
            "related_product_id": "MN-MOU-0001",
            "relation_type": "cheaper_than",
            "strength": 0.9,
        },
    ]
    data, report = _validate(records)

    assert len(data.product_relations) == 1
    assert len(_rejected(report, "Relations")) == 2


def test_relation_to_unknown_product_is_rejected():
    records = make_records()
    records["Relations"][0]["related_product_id"] = "MN-XXX-9999"
    data, report = _validate(records)
    assert data.product_relations == []
    assert "MN-XXX-9999" in _rejected(report, "Relations")[0].message


def test_findings_report_inactive_out_of_stock_and_duplicate_names():
    records = make_records()
    twin = dict(records["Products"][0], product_id="MN-HDP-0002", sku="HDP-2")
    records["Products"].append(twin)
    _, report = _validate(records)

    assert report.findings["inactive_products"] == ["MN-MOU-0001"]
    # MN-HDP-0002 has no inventory rows -> total stock 0
    assert report.findings["out_of_stock_products"] == ["MN-HDP-0002"]
    assert report.findings["duplicate_names"] == [
        {"name": "Nimbus Sound 1", "product_ids": ["MN-HDP-0001", "MN-HDP-0002"]}
    ]
