"""Cell-level cleanup: trim, Unicode NFC, NaN -> None, numpy/pandas types -> Python."""

import math
import unicodedata
from datetime import date, datetime
from typing import Any

import pandas as pd


def clean_value(value: Any) -> Any:
    """Normalize one Excel cell. Empty strings and NaN/NaT become None."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    if isinstance(value, float) and math.isnan(value):
        return None
    if value is pd.NA or value is pd.NaT:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        # numpy scalar (np.int64, np.bool_, np.float64) -> Python scalar
        return clean_value(value.item())
    if isinstance(value, str):
        text = unicodedata.normalize("NFC", value).strip()
        return text or None
    return value


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: clean_value(value) for key, value in record.items()}


def split_list(value: str | list[str] | None) -> list[str]:
    """'calls; gaming;  travel' -> ['calls', 'gaming', 'travel']. None -> []."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    items = (unicodedata.normalize("NFC", part).strip() for part in str(value).split(";"))
    return [item for item in items if item]


def to_date(value: date | datetime | None) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    return value
