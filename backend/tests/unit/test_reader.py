import math

import pandas as pd
import pytest

from app.ingest.reader import REQUIRED_COLUMNS, DatasetError, frames_to_records, read_workbook
from tests.factories import make_records


def _frames() -> dict[str, pd.DataFrame]:
    return {sheet: pd.DataFrame(rows) for sheet, rows in make_records().items()}


def test_frames_are_converted_to_clean_records():
    frames = _frames()
    frames["Products"].loc[0, "name"] = "  Nimbus Sound 1  "
    records = frames_to_records(frames)
    product = records["Products"][0]
    assert product["name"] == "Nimbus Sound 1"
    # NaN cells (pandas fills missing floats with NaN) come out as None, never NaN
    assert records["Products"][1]["weight_kg"] is None
    assert not any(isinstance(v, float) and math.isnan(v) for v in product.values())


def test_missing_sheet_is_fatal():
    frames = _frames()
    del frames["Pricing"]
    with pytest.raises(DatasetError, match="Missing sheet: Pricing"):
        frames_to_records(frames)


def test_missing_column_is_fatal():
    frames = _frames()
    frames["Inventory"] = frames["Inventory"].drop(columns=["reserved_qty"])
    with pytest.raises(DatasetError, match="reserved_qty"):
        frames_to_records(frames)


def test_extra_columns_are_ignored():
    frames = _frames()
    frames["Brands"]["unused"] = "x"
    assert "unused" not in frames_to_records(frames)["Brands"][0]
    assert set(REQUIRED_COLUMNS) == set(frames)


def test_missing_file_is_fatal(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        read_workbook(tmp_path / "nope.xlsx")
