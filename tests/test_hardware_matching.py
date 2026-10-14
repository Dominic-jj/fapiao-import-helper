"""真实税表上的五金简称、材质和历史冲突回归。"""

import pytest

from app.matching import match_items_with_ai
from core.models import Item
from core.tax_matcher import TaxMatcher


@pytest.fixture(scope='module')
def matcher(tmp_path_factory):
    path = tmp_path_factory.mktemp('hardware')
    return TaxMatcher(train_dir=str(path), alias_map_path='', confirmed_map_path=str(path / 'confirmed.json'), industry='hardware')


@pytest.mark.parametrize('name,expected', [
    ('公牛4位插座', '电路连接装置'), ('公牛有线14座', '电路连接装置'),
    ('电笔', '电磁参数测量仪器仪表'), ('介刀', '日常用刀及类似制品'),
    ('六角匙', '手动扳手及扳钳'), ('铁柄8齿扒', '农林牧通用金属手工具'),
    ('润滑脂', '润滑脂'), ('长鹿玻璃胶', '密封用粘胶品'),
    ('内牙阀芯', '阀门、龙头零件'), ('六类网线', '专用电缆'),
    ('沉头自钻', '钢铁制紧固件'), ('自钻头', '钢铁制紧固件'),
    ('水钻头', '钻孔或攻丝工具'), ('铜螺丝', '铜制紧固件'),
    ('不锈钢螺丝', '钢铁制紧固件'), ('铝铆钉', '铝制紧固件'),
    ('PVC电工胶布', '其他塑料制品'), ('橡胶电工胶布', '橡胶粘带'),
    ('PPR水管', '塑料管'), ('玻纤黄腊管', '玻璃纤维及其制品'),
    ('LED灯泡', '其他电光源'), ('羊毛扫', '刷子类制品'),
])
def test_clear_hardware_names_recall_real_tax_leaf(matcher, name, expected):
    candidates = matcher.match_candidates(name)
    assert candidates[0]['name'] == expected
    assert candidates[0]['is_leaf'] and not candidates[0]['requires_review']


@pytest.mark.parametrize('name', ['单合', '网管', '腊管', '深黄油', '喷雾黄油', '钢扎带', '拉爆', '生带', '大电工胶布', '手喷漆', '联塑直通', '开关', '滚筒'])
def test_missing_material_or_meaning_stays_unassigned(matcher, name):
    item = Item(name, '', '个', 1, 10, 10)
    stats = match_items_with_ai([item], matcher, None)
    assert not item.tax_code and item.tax_review_reason
    assert stats['needs_review'] == 1


def test_spec_resolves_material_without_rewriting_name(matcher):
    item = Item('螺丝', '铜 M6', '个', 1, 10, 10)
    match_items_with_ai([item], matcher, None)
    assert item.name == '螺丝' and item.spec == '铜 M6'
    assert item.tax_name == '铜制紧固件'


def test_stationery_substitution_history_requires_real_product_review(matcher):
    stationery = next(e for e in matcher.entries if e['is_leaf'] and e['name'] == '文具盒（袋）')
    matcher.train_map['长鹿明胶'] = stationery['code']
    try:
        candidates = matcher.match_candidates('长鹿明胶')
        assert candidates[0]['source'] == 'confirmed' and candidates[0]['requires_review']
        assert any(c['name'] == '密封用粘胶品' for c in candidates)
        item = Item('长鹿明胶', '', '支', 1, 10, 10)
        match_items_with_ai([item], matcher, None)
        assert not item.tax_code and '历史' in item.tax_review_reason
        assert matcher.train_map['长鹿明胶'] == stationery['code']
    finally:
        matcher.train_map.pop('长鹿明胶')


def test_matching_confirmed_history_has_priority_but_guessed_alias_does_not(matcher):
    steel = next(e for e in matcher.entries if e['name'] == '钢铁制紧固件')
    matcher.train_map['拉爆'] = steel['code']
    matcher.alias_map['介子'] = steel['code']
    try:
        assert matcher.match('拉爆')[0] == steel['code']
        assert matcher.match('介子') == ('', '')
    finally:
        matcher.train_map.pop('拉爆')
        matcher.alias_map.pop('介子')
