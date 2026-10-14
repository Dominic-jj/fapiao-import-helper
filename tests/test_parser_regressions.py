import pytest

from core.parser import parse_text_block, parse_text_line


@pytest.mark.parametrize("line", ["插座,个,1,100", "插座，个，1，100"])
def test_csv_delimiter_before_three_digit_price_is_preserved(line):
    item = parse_text_line(line)
    assert item is not None
    assert (item.name, item.unit, item.quantity, item.unit_price) == ("插座", "个", 1, 100)


@pytest.mark.parametrize("line", ["插座\t\t个\t2\t65\t130", "插座,,个,2,65,130"])
def test_blank_spec_does_not_shift_columns(line):
    item = parse_text_line(line)
    assert item is not None
    assert (item.spec, item.unit, item.quantity, item.unit_price) == ("", "个", 2, 65)


def test_quoted_csv_thousands_are_parsed_per_cell():
    item = parse_text_line('电线,米,"1,000",3.5')
    assert item.quantity == 1000
    assert item.amount == 3500


@pytest.mark.parametrize("value", ["nan", "inf", "-1", "1e309"])
def test_invalid_numbers_report_line_without_losing_valid_rows(value):
    items, errors = parse_text_block(f"插座 个 {value} 1\n电线 米 2 3")
    assert len(items) == len(errors) == 1
    assert errors[0].line_number == 1
    assert items[0].amount == 6


def test_finite_inputs_with_overflowing_amount_are_rejected():
    items, errors = parse_text_block("电线 米 1e200 1e200")
    assert not items
    assert len(errors) == 1
