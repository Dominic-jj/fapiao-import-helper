import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.matching import match_items  # noqa: E402
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


def make_item(name="漏电开关"):
    return Item(name=name, spec="", unit="个", quantity=1, unit_price=10, amount=10)


class MatchingServiceTest(unittest.TestCase):
    def test_known_missing_material_requires_review(self):
        item = make_item('水管')
        stats = match_items([item], _StubMatcher([{**LEAF, 'source':'hardware_rule'}]))
        self.assertEqual('', item.tax_code)
        self.assertEqual(1, stats['needs_review'])

    def test_confirmed_hit_uses_local_mapping(self):
        item = make_item()
        matcher = _StubMatcher([{**SAME_LEAF_BUT_CONFIRMED, 'reusable': True}])

        stats = match_items([item], matcher)

        self.assertEqual(1, stats["confirmed"])
        self.assertEqual(LEAF['code'], item.tax_code)
        self.assertEqual("confirmed", item.tax_match_source)
        self.assertTrue(item.tax_confirmed)

    def test_local_rule_suggestion_requires_confirmation(self):
        item = make_item()
        matcher = _StubMatcher([{**LEAF, 'source': 'hardware_rule', 'confidence': 'high', 'requires_review': False}])

        stats = match_items([item], matcher)

        self.assertEqual(1, stats["rule"])
        self.assertEqual(LEAF['code'], item.tax_code)
        self.assertEqual("hardware_rule", item.tax_match_source)
        self.assertFalse(item.tax_confirmed)

    def test_weak_local_candidate_needs_manual_review(self):
        item = make_item()
        matcher = _StubMatcher([LEAF])

        stats = match_items([item], matcher)

        self.assertEqual("", item.tax_code)
        self.assertEqual(1, stats["needs_review"])

    def test_no_candidates_needs_manual_confirmation(self):
        item = make_item()
        matcher = _StubMatcher([])

        stats = match_items([item], matcher)

        self.assertEqual(1, stats["unmatched"])
        self.assertEqual("", item.tax_code)
        self.assertTrue(stats["done"])

    def test_progress_callback_receives_each_step(self):
        matcher = _StubMatcher([LEAF])
        messages = []

        match_items(
            [make_item()],
            matcher,
            progress_callback=lambda stats, message: messages.append(message),
        )

        self.assertTrue(any("正在匹配" in message for message in messages))
        self.assertTrue(any("已完成" in message or "处理完成" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
