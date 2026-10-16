"""Doc135 physical-unit normalization; no instrument multiplier lookup tables."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ashare_export_supplement_inputs import normalized_contract_multiplier


def test_actual_jd_500kg_quote_is_not_per_unit():
    # Actual JD1907.DCE source object:
    # 0cdf2ef67ad0ecfd19aad0fef8cf2804f77a27c607555f95ceb7691c54481092.
    value = normalized_contract_multiplier({
        "multiplier": None, "per_unit": 5, "trade_unit": "吨",
        "quote_unit": "人民币元/500千克", "quote_unit_desc": "1人民币元/500千克",
    })
    assert value["normalized_multiplier"] == 10
    assert value["normalized_multiplier"] != 5
    assert value["currency"] == "CNY"


def test_same_unit_quantity_is_nominal_multiplier_not_tick_size():
    value = normalized_contract_multiplier({
        "per_unit": 20, "trade_unit": "吨", "quote_unit": "人民币元/吨",
        "quote_unit_desc": "0.5人民币元/吨",
    })
    assert value["normalized_multiplier"] == 20


@pytest.mark.parametrize("quantity,trade,quote,expected", [
    (1, "千克", "人民币元/克", 1000),
    (1000, "克", "人民币元/千克", 1),
    (1000, "桶", "人民币元/桶", 1000),
])
def test_physical_dimensions_include_gold_mass_units(quantity, trade, quote, expected):
    assert normalized_contract_multiplier({
        "per_unit": quantity, "trade_unit": trade, "quote_unit": quote,
    })["normalized_multiplier"] == expected


@pytest.mark.parametrize("fields", [
    {"per_unit": 5, "trade_unit": "未知单位", "quote_unit": "人民币元/吨"},
    {"per_unit": 5, "trade_unit": "吨", "quote_unit": "USD/吨"},
    {"per_unit": 5, "trade_unit": "吨", "quote_unit": "人民币元/桶"},
    {"per_unit": None, "trade_unit": "吨", "quote_unit": "人民币元/吨"},
    {"per_unit": 0, "trade_unit": "吨", "quote_unit": "人民币元/吨"},
    {"per_unit": 5, "trade_unit": "吨", "quote_unit": None},
])
def test_unknown_or_incompatible_dimensions_fail_closed(fields):
    with pytest.raises(ValueError):
        normalized_contract_multiplier(fields)
