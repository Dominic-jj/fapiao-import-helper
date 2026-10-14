import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.matching import match_items_with_ai  # noqa: E402
from core.models import Item  # noqa: E402


LEAF = {
    "code": "1090407040000000000",
    "name": "配电或电器控制设备",
    "category": "开关设备",
    "is_leaf": True,
    "source": "tax_list",
    "score": 10,
    "confidence": "low", "requires_review": True,
}
SAME_LEAF_BUT_CONFIRMED = {**LEAF, "source": "confirmed", "score": 9999, "confidence": "high", "requires_review": False}


class _StubMatcher:
    def __init__(self, candidates):
        self._candidates = candidates

    def match_candidates(self, item_name, top_n=20, **kwargs):
        return [dict(candidate) for candidate in self._candidates]


class _StubAI:
    def __init__(self, result=None, available=True):
        self._result = result
        self._available = available
        self.unavailable_reason = "" if available else "未配置 DEEPSEEK_API_KEY，已跳过 AI 辅助重排"
        self.calls = 0

    def is_available(self):
        return self._available

    def suggest_search_terms(self, item_name, **kwargs):
        return None

    def rerank_candidate(self, item_name, candidates, **kwargs):
        self.calls += 1
        if not self._result:
            return None
        selected = {**candidates[0], **self._result}
        if "source" not in self._result:
            selected["source"] = "ai_rerank"
        return selected


def make_item(name="漏电开关"):
    return Item(name=name, spec="", unit="个", quantity=1, unit_price=10, amount=10)


class MatchingServiceTest(unittest.TestCase):
    def test_semantic_recall_can_find_candidate_absent_from_original_pool(self):
        target = {**LEAF, 'code': '1070101080000000000', 'name': '润滑脂'}
        class SemanticMatcher:
            def match_candidates(self, name, **kwargs):
                return [target] if name == '润滑脂' else []
        class SemanticAI(_StubAI):
            def suggest_search_terms(self, name, **kwargs):
                return {'standard_name':'润滑脂', 'search_terms':['润滑脂'], 'confidence':'high', 'needs_confirmation':False, 'reason':''}
        item = make_item('陌生润滑简称')
        ai = SemanticAI({'confidence':'high', 'requires_review':False})
        stats = match_items_with_ai([item], SemanticMatcher(), ai)
        self.assertEqual(target['code'], item.tax_code)
        self.assertEqual(1, stats['ai_interpreted'])

    def test_known_missing_material_is_not_guessed_by_ai(self):
        item = make_item('水管')
        ai = _StubAI({'confidence':'high', 'requires_review':False})
        stats = match_items_with_ai([item], _StubMatcher([{**LEAF, 'source':'hardware_rule'}]), ai)
        self.assertEqual(0, ai.calls)
        self.assertEqual('', item.tax_code)
        self.assertEqual(1, stats['needs_review'])

    def test_medium_ai_result_remains_reviewable(self):
        item = make_item()
        match_items_with_ai([item], _StubMatcher([LEAF]), _StubAI({'confidence':'medium', 'requires_review':True}))
        self.assertEqual('', item.tax_code)

    def test_confirmed_hit_skips_ai(self):
        item = make_item()
        matcher = _StubMatcher([SAME_LEAF_BUT_CONFIRMED])
        ai = _StubAI({"code": "1070215030000000000"})

        stats = match_items_with_ai([item], matcher, ai)

        self.assertEqual(1, stats["confirmed"])
        self.assertEqual(0, ai.calls)
        self.assertEqual("confirmed", item.tax_match_source)

    def test_rule_hit_is_reranked_by_ai(self):
        item = make_item()
        matcher = _StubMatcher([LEAF])
        ai = _StubAI({"ai_confidence": "high", "confidence": "high", "requires_review": False})

        stats = match_items_with_ai([item], matcher, ai)

        self.assertEqual(1, ai.calls)
        self.assertEqual(1, stats["ai_success"])
        self.assertEqual("ai_rerank", item.tax_match_source)
        self.assertEqual("high", item.tax_ai_confidence)

    def test_ai_failure_keeps_weak_rule_for_manual_review(self):
        item = make_item()
        matcher = _StubMatcher([LEAF])
        ai = _StubAI(None)

        stats = match_items_with_ai([item], matcher, ai)

        self.assertEqual(1, stats["ai_attempted"])
        self.assertEqual(1, stats["ai_fallback"])
        self.assertEqual("", item.tax_code)
        self.assertEqual(1, stats["needs_review"])

    def test_ai_unavailable_is_reported(self):
        item = make_item()
        matcher = _StubMatcher([LEAF])
        ai = _StubAI(None, available=False)

        stats = match_items_with_ai([item], matcher, ai)

        self.assertEqual(0, ai.calls)
        self.assertEqual(1, stats["ai_skipped"])
        self.assertFalse(stats["ai_available"])
        self.assertIn("DEEPSEEK_API_KEY", stats["ai_skip_reason"])

    def test_no_candidates_needs_manual_confirmation(self):
        item = make_item()
        matcher = _StubMatcher([])

        stats = match_items_with_ai([item], matcher, _StubAI())

        self.assertEqual(1, stats["unmatched"])
        self.assertEqual("", item.tax_code)
        self.assertTrue(stats["done"])

    def test_progress_callback_receives_each_step(self):
        matcher = _StubMatcher([LEAF])
        messages = []

        match_items_with_ai(
            [make_item()],
            matcher,
            _StubAI(),
            progress_callback=lambda stats, message: messages.append(message),
        )

        self.assertTrue(any("正在匹配" in message for message in messages))
        self.assertTrue(any("已完成" in message or "处理完成" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
