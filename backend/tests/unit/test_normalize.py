import math
import unicodedata

import numpy as np
import pandas as pd

from app.ingest.normalize import clean_value, split_list


def test_nan_nat_and_blank_become_none():
    assert clean_value(math.nan) is None
    assert clean_value(np.float64("nan")) is None
    assert clean_value(pd.NaT) is None
    assert clean_value("   ") is None
    assert clean_value(None) is None


def test_strings_are_trimmed_and_nfc():
    decomposed = unicodedata.normalize("NFD", "  Canelón  ")
    assert clean_value(decomposed) == "Canelón"
    assert clean_value(decomposed) == unicodedata.normalize("NFC", "Canelón")


def test_numpy_scalars_become_python():
    assert type(clean_value(np.int64(3))) is int
    assert clean_value(np.bool_(False)) is False
    assert type(clean_value(pd.Timestamp("2026-01-02"))).__name__ == "datetime"


def test_split_list_trims_and_drops_empty_items():
    assert split_list("calls;  video calls ; ;gaming;") == ["calls", "video calls", "gaming"]
    assert split_list(None) == []
    assert split_list("") == []
