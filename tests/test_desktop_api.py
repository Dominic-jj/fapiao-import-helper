from unittest.mock import Mock
from inspect import getfullargspec
from concurrent.futures import ThreadPoolExecutor

import openpyxl
import pytest

from app.api import DesktopAPI
from core.tax_matcher import TaxMatcher


@pytest.fixture
def api(tmp_path, monkeypatch):
    matcher = TaxMatcher(train_dir=str(tmp_path), alias_map_path="", confirmed_map_path=str(tmp_path / "confirmed.json"))
    monkeypatch.setattr("app.api.TaxMatcher", lambda: matcher)
    monkeypatch.setattr("app.api.ensure_user_resources", lambda: None)
    monkeypatch.setattr('app.api.load_settings', lambda: {'ai_enabled': False, 'industry': 'hardware'})
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    return DesktopAPI()


def parsed(api):
    return api.parse_text("漏电开关 个 1 65")["items"][0]


def test_spec_edit_recalculates_material_and_manual_choice_is_preserved(api):
    item = api.parse_text('铜 螺丝 个 1 10')['items'][0]
    # 铜作为名称前缀也能提供材质；换成钢材规格应重新匹配。
    item = api.update_item(item['row_id'], {'name':'螺丝', 'spec':'铜 M6'})['items'][0]
    assert item['tax_name'] == '铜制紧固件'
    item = api.update_item(item['row_id'], {'spec':'不锈钢 M6'})['items'][0]
    assert item['tax_name'] == '钢铁制紧固件'
    api.select_tax(item['row_id'], item['tax_code'])
    item = api.update_item(item['row_id'], {'spec':'铜 M6'})['items'][0]
    assert item['tax_name'] == '钢铁制紧固件' and item['tax_match_source'] == 'manual'
    assert not item['tax_confirmed']
    assert any('尚未确认' in message for message in api._validation_errors())


def test_unassigned_quantity_edit_does_not_repeat_matching(api):
    item = api.parse_text('单合 个 1 10')['items'][0]
    assert not item['tax_code']
    api._ai_classifier.suggest_search_terms = Mock()
    api._match_items = Mock()
    api.update_item(item['row_id'], {'quantity':2})
    api._match_items.assert_called_once_with([])


def test_review_required_blocks_export_until_manual_selection(api):
    item = api.parse_text('手喷漆 瓶 1 10')['items'][0]
    assert not item['tax_code'] and 'VOC' in item['tax_review_reason']
    assert not api.export_invoice()['ok']
    candidates = api.search_tax(item['name'])
    assert candidates and api.select_tax(item['row_id'], candidates[0]['code'])['ok']
    assert not api._validation_errors()


def test_product_candidates_precede_conflicting_old_stationery(api):
    stationery = next(e for e in api._matcher.entries if e['name'] == '文具盒（袋）')
    api._matcher.train_map['长鹿明胶'] = stationery['code']
    candidates = api.search_tax('长鹿明胶')
    assert candidates[0]['name'] == '密封用粘胶品'
    assert any(c['code'] == stationery['code'] and c['requires_review'] for c in candidates)


def test_bridge_can_discover_api_arguments(api):
    assert getfullargspec(api.parse_text).args == ["self", "text"]
    assert getfullargspec(api.update_item).args == ["self", "row_id", "values"]
    assert getfullargspec(api.update_items).args == ["self", "rows"]


def test_parallel_bridge_calls_keep_unique_row_ids(api):
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: api.add_item(), range(20)))
    ids = [item["row_id"] for item in api.get_state()["items"]]
    assert len(ids) == len(set(ids)) == 20


@pytest.mark.parametrize("value", ["", "abc", "nan", "inf", "-1", "1e309"])
def test_invalid_edit_keeps_original_item(api, value):
    before = parsed(api)
    with pytest.raises(ValueError):
        api.update_item(before["row_id"], {"name": "新名称", "quantity": value})
    assert api.get_state()["items"][0] == before


def test_batch_update_is_atomic_and_computes_latest_amount(api):
    items = api.parse_text("漏电开关 个 1 65\n电线 米 2 3")["items"]
    with pytest.raises(ValueError):
        api.update_items([
            {"row_id": items[0]["row_id"], "quantity": 3},
            {"row_id": items[1]["row_id"], "unit_price": "invalid"},
        ])
    assert api.get_state()["items"] == items
    updated = api.update_items([{"row_id": items[0]["row_id"], "quantity": 3}])
    assert updated["items"][0]["amount"] == 195


def test_manual_selection_survives_rematch_and_quantity_edit(api):
    item = parsed(api)
    other = next(entry for entry in api._matcher.entries if entry["is_leaf"] and entry["code"] != item["tax_code"])
    api.select_tax(item["row_id"], other["code"])
    api.update_item(item["row_id"], {"quantity": 2})
    result = api.rematch()["items"][0]
    assert result["tax_code"] == other["code"]
    assert result["tax_match_source"] == "manual"


def test_rename_clears_manual_tax_and_confidence(api):
    item = parsed(api)
    api.select_tax(item["row_id"], item["tax_code"])
    api._items[0].tax_ai_confidence = "high"
    result = api.update_item(item["row_id"], {"name": ""})["items"][0]
    assert result["tax_code"] == result["tax_ai_confidence"] == ""


def test_row_ids_not_reused_after_clear_or_reparse(api):
    old_id = parsed(api)["row_id"]
    api.clear_items()
    new_id = parsed(api)["row_id"]
    assert new_id > old_id
    assert parsed(api)["row_id"] > new_id
    with pytest.raises(ValueError):
        api.select_tax(old_id, "1090407040000000000")


def test_search_finds_code_category_and_alternatives_to_history(api):
    item = parsed(api)
    entry = api._matcher.get_entry(item["tax_code"])
    assert api.search_tax(entry["code"])[0]["code"] == entry["code"]
    assert any(candidate["code"] == entry["code"] for candidate in api.search_tax(entry["category"]))
    api._matcher.confirmed_map["开关"] = entry["code"]
    assert len(api.search_tax("开关")) > 1


def test_conflicting_same_names_are_not_silently_saved(api):
    items = api.parse_text("漏电开关 个 1 65\n漏电开关 个 2 70")["items"]
    other = next(entry for entry in api._matcher.entries if entry["is_leaf"] and entry["code"] != items[0]["tax_code"])
    api.select_tax(items[1]["row_id"], other["code"])
    result = api.save_confirmations()
    assert result["saved"] == 0
    assert result["errors"]
    assert not api._matcher.confirmed_map


def test_parse_failures_block_incomplete_export(api):
    api.parse_text("漏电开关 个 1 65\n缺少字段")
    api._window = Mock()
    result = api.export_invoice()
    assert not result["ok"]
    assert "未解析" in result["message"]
    api._window.create_file_dialog.assert_not_called()


def test_export_uses_latest_values_and_actual_template(api, tmp_path):
    item = parsed(api)
    api.select_tax(item['row_id'], item['tax_code'])
    api.update_item(item["row_id"], {"quantity": 3})
    output = tmp_path / "invoice.xlsx"
    api._window = Mock()
    api._window.create_file_dialog.return_value = (str(output),)
    assert api.export_invoice()["ok"]
    wb = openpyxl.load_workbook(output)
    try:
        assert wb["1-明细模板"]["G4"].value == 195
        assert wb["1-明细模板"]["B4"].data_type == "s"
    finally:
        wb.close()


def test_export_cancel_and_write_failure_are_reported(api):
    item = parsed(api)
    api.select_tax(item['row_id'], item['tax_code'])
    api._window = Mock()
    api._window.create_file_dialog.return_value = None
    assert api.export_invoice()["cancelled"]
    api._window.create_file_dialog.side_effect = OSError("dialog unavailable")
    assert not api.export_invoice()["ok"]


def test_full_tax_catalog_bypasses_history_and_only_leaf_can_be_selected(api):
    item = parsed(api)
    copper = next(e for e in api._matcher.entries if e['name'] == '铜制紧固件')
    api._matcher.confirmed_map['铜制紧固件'] = item['tax_code']
    result = api.browse_tax_catalog('铜制紧固件')
    assert result['items'][0]['code'] == copper['code']
    detail = api.tax_catalog_detail(copper['code'])
    assert detail['path'] and detail['is_leaf']
    parent = next(e for e in api._matcher.entries if not e['is_leaf'])
    assert not api.select_tax(item['row_id'], parent['code'])['ok']
    assert api.select_tax(item['row_id'], detail['code'])['state']['items'][0]['tax_confirmed']
