from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import openpyxl
import pytest

from app.api import DesktopAPI
from core.invoice_writer import generate
from core.models import Item
from core.tax_matcher import TaxMatcher


@pytest.fixture
def create_api(tmp_path, monkeypatch):
    def create(industry='hardware'):
        matcher = TaxMatcher(train_dir=str(tmp_path / 'history'), alias_map_path='',
            confirmed_map_path=str(tmp_path / 'confirmed.json'), industry=industry)
        monkeypatch.setattr('app.api.TaxMatcher', lambda: matcher)
        monkeypatch.setattr('app.api.ensure_user_resources', lambda: None)
        monkeypatch.setattr('app.api.load_settings', lambda: {'ai_enabled': False, 'industry': industry})
        return DesktopAPI(draft_path=str(tmp_path / 'draft.json'))
    return create


def test_suggestion_requires_confirmation_before_export_and_save(create_api):
    api = create_api()
    item = api.parse_text('漏电开关 个 1 65')['items'][0]
    assert item['tax_code'] and not item['tax_confirmed']
    api._window = Mock()
    assert '尚未确认' in api.export_invoice()['message']
    assert api.save_confirmations()['saved'] == 0
    api._window.create_file_dialog.assert_not_called()
    api.select_tax(item['row_id'], item['tax_code'])
    assert not api._validation_errors()
    assert api.save_confirmations()['saved'] == 1


def test_restart_restores_raw_text_final_edit_and_manual_choice(create_api):
    api = create_api()
    item = api.parse_text('漏电开关 个 1 65')['items'][0]
    api.select_tax(item['row_id'], item['tax_code'])
    api.update_item(item['row_id'], {'quantity': 3, 'tax_rate': '0.03'})
    api.save_input('还没有解析的输入')
    restored = create_api().get_state()
    assert restored['raw_text'] == '还没有解析的输入'
    assert restored['items'][0]['amount'] == 195
    assert restored['items'][0]['tax_confirmed']
    assert restored['items'][0]['tax_rate'] == '0.03'


def test_empty_editable_row_and_clear_survive_restart(create_api):
    api = create_api()
    api.add_item()
    assert len(create_api().get_state()['items']) == 1
    api.clear_items()
    assert create_api().get_state()['items'] == []


def test_corrupt_draft_is_retained_before_new_draft(create_api, tmp_path):
    (tmp_path / 'draft.json').write_text('{broken', encoding='utf-8')
    api = create_api()
    assert '原文件已保留' in api.get_state()['draft_message']
    assert (tmp_path / 'draft.json').read_text() == '{broken'
    api.save_input('新文本')
    assert list(tmp_path.glob('draft-corrupt-*.json'))[0].read_text() == '{broken'


def test_confirmed_contexts_coexist_and_reuse_without_size_collision(tmp_path):
    matcher = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path=str(tmp_path / 'confirmed.json'))
    steel = next(e for e in matcher.entries if e['name'] == '钢铁制紧固件')
    copper = next(e for e in matcher.entries if e['name'] == '铜制紧固件')
    assert matcher.save_confirmed_tax_code('螺丝', steel['code'], spec='不锈钢 M6', unit='个')[0]
    assert matcher.save_confirmed_tax_code('螺丝', copper['code'], spec='铜 M6', unit='个')[0]
    reloaded = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path=str(tmp_path / 'confirmed.json'))
    assert len(reloaded.confirmed_records) == 2
    candidate = reloaded.match_candidates('螺丝', spec='铜 M8', unit='个')[0]
    assert candidate['code'] == copper['code'] and candidate['reusable']
    # 新确认存在上下文时，缺少上下文不能回退为最后一条名称映射。
    assert not reloaded.match_candidates('螺丝')[0].get('reusable', False)


def test_history_preserves_properties_conflicts_and_rejects_unknown_layout(tmp_path):
    matcher = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path='')
    entries = [e for e in matcher.entries if e['is_leaf']][:2]
    for index, spec in enumerate(['材料甲', '材料乙']):
        generate([Item('合成商品', spec, '个', 1, 1, 1, tax_code=entries[index]['code'])], str(tmp_path / f'{index}.xlsx'))
    wrong = openpyxl.Workbook()
    wrong.save(tmp_path / 'unknown.xlsx')
    wrong.close()
    loaded = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path='')
    assert len(loaded.history_records) == 2
    assert loaded.match_candidates('合成商品', spec='材料乙', unit='个')[0]['code'] == entries[1]['code']
    assert len(loaded.match_candidates('合成商品')) == 2
    assert loaded.history_stats['ignored'] == 1


@pytest.mark.parametrize('industry', ['', 'hardware'])
def test_generic_products_are_not_forced_into_hardware(tmp_path, industry):
    matcher = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path='', industry=industry)
    for name in ['滚筒洗衣机', '儿童塑料玩具剪刀']:
        assert all(c.get('source') != 'hardware_rule' for c in matcher.match_candidates(name))


def test_ai_runs_outside_edit_lock_and_cancel_discards_result(create_api, monkeypatch):
    api = create_api(industry='')
    item = api.parse_text('陌生商品 个 1 10')['items'][0]
    api._ai_enabled = True
    api._ai_classifier.is_available = lambda: True
    entered, release = Event(), Event()
    def delayed(items, matcher, classifier):
        entered.set()
        assert release.wait(5)
        items[0].tax_code = next(e['code'] for e in matcher.entries if e['is_leaf'])
    monkeypatch.setattr('app.api.match_items_with_ai', delayed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        future = executor.submit(api.assist_tax, item['row_id'])
        assert entered.wait(5)
        api.update_item(item['row_id'], {'quantity': 2})
        api.cancel_ai(item['row_id'])
        release.set()
        assert not future.result(5)['ok']
    assert api.get_state()['items'][0]['amount'] == 20
    assert not api.get_state()['items'][0]['tax_confirmed']


def test_invalid_tax_rates_cannot_enter_export(create_api):
    api = create_api()
    item = api.parse_text('漏电开关 个 1 65')['items'][0]
    for value in ['', 'nan', 'inf', '-0.1', '1.01']:
        with pytest.raises(ValueError):
            api.update_item(item['row_id'], {'tax_rate': value})


def test_real_import_history_conflict_remains_reviewable(tmp_path):
    matcher = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path='', industry='hardware')
    wrong = next(e for e in matcher.entries if e['name'] == '文具盒（袋）')
    generate([Item('硅酮胶', '', '支', 1, 1, 1, tax_code=wrong['code'])], str(tmp_path / 'history.xlsx'))
    loaded = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path='', industry='hardware')
    candidates = loaded.match_candidates('硅酮胶', unit='支')
    assert candidates[0]['requires_review'] and '不符' in candidates[0]['review_reason']
    assert any(c['name'] == '密封用粘胶品' for c in candidates)


def test_generic_material_spec_ranks_relevant_candidate_but_requires_review(tmp_path):
    matcher = TaxMatcher(train_dir=str(tmp_path), alias_map_path='', confirmed_map_path='')
    candidates = matcher.match_candidates('螺丝', spec='铜 M6', unit='个')
    assert candidates[0]['name'] == '铜制紧固件'
    assert candidates[0]['requires_review']


def test_same_context_ai_requests_share_one_call(create_api, monkeypatch):
    api = create_api(industry='')
    rows = api.parse_text('陌生商品 个 1 10\n陌生商品 个 2 10')['items']
    api._ai_enabled = True
    api._ai_classifier.is_available = lambda: True
    entered, release = Event(), Event()
    calls = []
    def delayed(items, matcher, classifier):
        calls.append(1)
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr('app.api.match_items_with_ai', delayed)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(api.assist_tax, rows[0]['row_id'])
        assert entered.wait(5)
        second = executor.submit(api.assist_tax, rows[1]['row_id'])
        release.set()
        assert first.result(5)['ok'] and second.result(5)['ok']
    assert len(calls) == 1


def test_draft_write_failure_preserves_previous_good_file(create_api, tmp_path, monkeypatch):
    api = create_api()
    api.save_input('有效输入')
    before = (tmp_path / 'draft.json').read_bytes()
    monkeypatch.setattr('app.api.write_json', Mock(side_effect=OSError('disk unavailable')))
    api.save_input('新的输入')
    assert (tmp_path / 'draft.json').read_bytes() == before
    assert '保存失败' in api.get_state()['draft_message']
