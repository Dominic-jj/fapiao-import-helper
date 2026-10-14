"""历史确认、五金品名解释、本地税编召回和可选 AI 复核。"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from core.ai_classifier import AIClassifier
from core.models import Item
from core.tax_matcher import TaxMatcher

CANDIDATE_TOP_N = 30
ProgressCallback = Callable[[dict, str], None]


def make_match_stats(total: int, ai_classifier: AIClassifier | None) -> dict:
    available = bool(ai_classifier and ai_classifier.is_available())
    return {
        'total': total, 'processed': 0, 'confirmed': 0, 'alias': 0, 'rule': 0,
        'ai_attempted': 0, 'ai_success': 0, 'ai_fallback': 0, 'ai_skipped': 0,
        'ai_interpreted': 0, 'needs_review': 0, 'unmatched': 0,
        'ai_available': available,
        'ai_skip_reason': '' if available else getattr(ai_classifier, 'unavailable_reason', '') or ('AI 辅助已关闭' if ai_classifier is None else 'AI 辅助不可用，已跳过 AI'),
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


def match_items_with_ai(
    items: Sequence[Item], matcher: TaxMatcher, ai_classifier: AIClassifier | None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    stats = make_match_stats(len(items), ai_classifier)
    _notify(progress_callback, stats, '准备读取历史确认和真实商品线索')
    for item in items:
        _notify(progress_callback, stats, f'正在匹配 {item.name}')
        candidates = matcher.match_candidates(item.name, top_n=CANDIDATE_TOP_N, spec=item.spec, unit=item.unit)
        selected = candidates[0] if candidates else None
        kind = _count_source(stats, selected.get('source', '')) if selected else 'rule'
        interpretation = None
        # 历史冲突或材质/VOC未明的已知五金商品必须人工复核；不让模型编造缺失信息。
        known_or_confirmed = selected and (kind != 'rule' or selected.get('source') == 'hardware_rule')
        strong = selected and selected.get('confidence') == 'high' and not selected.get('requires_review')
        if not known_or_confirmed and not strong:
            if stats['ai_available']:
                stats['ai_attempted'] += 1
                _notify(progress_callback, stats, f'AI 正在解释和复核 {item.name}')
                interpretation = ai_classifier.suggest_search_terms(item.name, spec=item.spec, unit=item.unit)
                if interpretation:
                    stats['ai_interpreted'] += 1
                    pool = {}
                    for term in interpretation['search_terms']:
                        for candidate in matcher.match_candidates(term, top_n=10, spec=item.spec, unit=item.unit):
                            # 从搜索词召回时不复用别的商品的人工历史记录。
                            if candidate.get('source', '').startswith(('confirmed', 'alias')):
                                continue
                            pool.setdefault(candidate['code'], candidate)
                    for candidate in candidates:
                        pool.setdefault(candidate['code'], candidate)
                    candidates = list(pool.values())[:CANDIDATE_TOP_N]
                ai_selected = ai_classifier.rerank_candidate(
                    item.name, candidates, spec=item.spec, unit=item.unit, interpretation=interpretation,
                ) if candidates else None
                if ai_selected:
                    selected = ai_selected
                    if interpretation:
                        selected['standard_name'] = interpretation['standard_name']
                        if interpretation['needs_confirmation'] or interpretation['confidence'] != 'high':
                            selected['requires_review'] = True
                            selected['review_reason'] = interpretation['reason'] or '商品简称解释不确定，请确认真实商品'
                    if selected.get('code') and not selected.get('requires_review'):
                        stats['ai_success'] += 1
                    else:
                        stats['ai_fallback'] += 1
                else:
                    stats['ai_fallback'] += 1
            else:
                stats['ai_skipped'] += 1

        item.tax_code = item.tax_name = item.tax_match_source = item.tax_ai_confidence = ''
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
            item.tax_ai_confidence = selected.get('ai_confidence', '')
            item.tax_confirmed = bool(selected.get('reusable', False))
            if kind == 'rule':
                stats['rule'] += 1
        stats['processed'] += 1
        _notify(progress_callback, stats, f'{item.name}：{item.tax_review_reason or item.tax_name}')
    stats['done'] = True
    _notify(progress_callback, stats, '全部税编候选处理完成')
    return stats
