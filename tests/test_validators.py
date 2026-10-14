import pytest

from core.models import Item
from core.validators import to_float, validate_item


@pytest.mark.parametrize("value", [None, "", "abc", "nan", "inf", "1e309"])
def test_nonfinite_or_invalid_number_is_rejected(value):
    assert to_float(value) is None


def test_unit_price_precision_and_thousands_are_preserved():
    assert to_float("1,000.125") == 1000.125
    assert to_float("1，000.125") == 1000.125


def test_errors_use_stable_row_id():
    errors = validate_item(Item("", "", "", -1, float("nan"), 0, row_id=12))
    assert len(errors) == 4
    assert all(error.startswith("第 12 行") for error in errors)


def test_amount_overflow_is_rejected():
    assert validate_item(Item("电线", "", "米", 1e200, 1e200, 0))
