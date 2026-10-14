import pytest

from core.tax_catalog import TaxCatalog


@pytest.fixture
def catalog():
    return TaxCatalog([
        {'code': '1000000000000000000', 'name': '货物', 'category': '', 'desc': '', 'is_leaf': False},
        {'code': '1080000000000000000', 'name': '金属制品', 'category': '金属', 'desc': '', 'is_leaf': False},
        {'code': '1080402000000000000', 'name': '紧固件', 'category': '紧固件', 'desc': '', 'is_leaf': False},
        {'code': '1080402010000000000', 'name': '钢铁制紧固件', 'category': '金属制品', 'desc': '用于连接的钢铁制螺钉。', 'is_leaf': True},
        {'code': '1080402020000000000', 'name': '铜制紧固件', 'category': '金属制品', 'desc': '用于连接的铜制螺钉。完整说明。', 'is_leaf': True},
        {'code': '2000000000000000000', 'name': '劳务', 'category': '', 'desc': '', 'is_leaf': True},
    ])


def test_browse_roots_children_and_complete_detail(catalog):
    roots = catalog.browse()
    assert [e['name'] for e in roots['items']] == ['货物', '劳务']
    assert catalog.browse(parent_code='1080402000000000000')['total'] == 2
    detail = catalog.detail('1080402020000000000')
    assert [e['name'] for e in detail['path']] == ['货物', '金属制品', '紧固件', '铜制紧固件']
    assert detail['desc'].endswith('完整说明。') and detail['is_leaf']
    assert not catalog.detail('1080402000000000000')['is_leaf']
    assert catalog.browse(parent_code='2000000000000000000')['items'][0]['name'] == '劳务'


def test_searches_full_table_description_multiple_terms_and_scope(catalog):
    assert catalog.browse(query='铜 螺钉')['items'][0]['name'] == '铜制紧固件'
    assert catalog.browse(query='108040202')['items'][0]['name'] == '铜制紧固件'
    assert catalog.browse(query='螺钉', parent_code='2000000000000000000')['total'] == 0
    assert catalog.browse(leaf_only=True)['total'] == 3


def test_paging_clamps_and_unknown_code_is_rejected(catalog):
    first = catalog.browse(query='金属', page_size=1)
    second = catalog.browse(query='金属', page_size=1, offset=1)
    assert first['items'][0]['code'] != second['items'][0]['code']
    assert catalog.browse(query='无结果', offset=999)['offset'] == 0
    assert catalog.browse(page_size=999)['page_size'] == 100
    with pytest.raises(ValueError):
        catalog.detail('999')
    with pytest.raises(ValueError):
        catalog.browse(parent_code='999')
