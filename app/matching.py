"""历史确认、五金品名解释和本地税编候选匹配。"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from core.models import Item
from core.tax_matcher import TaxMatcher

CANDIDATE_TOP_N = 30
ProgressCallback = Callable[[dict, str], None]


def make_match_stats(total: int) -> dict:
    return {
        'total': total, 'processed': 0, 'confirmed': 0, 'alias': 0, 'rule': 0,
        'needs_review': 0, 'unmatched': 0,
        'done': False,
    }


def _notify(callback, stats, message):
    if callback:
        callback(stats, message)


def _count_source(stats, source):
    if source.startswith(('confirmed', 'history')):
        stats['confirmed'] += 1
        return 'confirmed'
    if source.startswith('alias'):
        stats['alias'] += 1
        return 'alias'
    return 'rule'


def match_items(
    items: Sequence[Item], matcher: TaxMatcher,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    stats = make_match_stats(len(items))
    _notify(progress_callback, stats, '准备读取历史确认和真实商品线索')
    for item in items:
        _notify(progress_callback, stats, f'正在匹配 {item.name}')
        candidates = matcher.match_candidates(item.name, top_n=CANDIDATE_TOP_N, spec=item.spec, unit=item.unit)
        selected = candidates[0] if candidates else None
        kind = _count_source(stats, selected.get('source', '')) if selected else 'rule'
        item.tax_code = item.tax_name = item.tax_match_source = ''
        item.tax_confirmed = False
        item.tax_match_confidence = selected.get('confidence', '') if selected else ''
        item.tax_standard_name = selected.get('standard_name', '') if selected else ''
        item.tax_review_reason = ''
        if not selected:
            stats['unmatched'] += 1
            item.tax_review_reason = '没有可靠候选，请补充完整商品名称、规格或手动选择'
        elif selected.get('requires_review'):
            stats['needs_review'] += 1
            item.tax_review_reason = selected.get('review_reason') or '请确认真实商品、材质与用途'
        else:
            item.tax_code, item.tax_name = selected['code'], selected['name']
            item.tax_match_source = selected.get('source', '')
            item.tax_confirmed = bool(selected.get('reusable', False))
            if kind == 'rule':
                stats['rule'] += 1
        stats['processed'] += 1
        _notify(progress_callback, stats, f'{item.name}：{item.tax_review_reason or item.tax_name}')
    stats['done'] = True
    _notify(progress_callback, stats, '全部税编候选处理完成')
    return stats
