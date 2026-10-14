import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.ai_classifier import AIClassifier  # noqa: E402


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self.content)


class _Chat:
    def __init__(self, content):
        self.completions = _Completions(content)


class _Client:
    def __init__(self, content):
        self.chat = _Chat(content)


class AIClassifierTest(unittest.TestCase):
    def test_intentional_abstention_is_not_retried(self):
        classifier = AIClassifier(api_key='test')
        classifier.client = _Client('{"code":"","confidence":"low","reason":"材质缺失"}')
        selected = classifier.rerank_candidate('不明管', [{'code':'1', 'name':'塑料管', 'is_leaf':True}])
        self.assertTrue(selected['requires_review'])
        self.assertEqual('', selected['code'])
        self.assertEqual(1, len(classifier.client.chat.completions.calls))

    def test_medium_confidence_is_not_exposed_as_final_classification(self):
        classifier = AIClassifier(api_key='test')
        classifier.client = _Client('{"code":"1","confidence":"medium"}')
        candidates = [{'code':'1', 'name':'塑料管', 'is_leaf':True}]
        self.assertTrue(classifier.rerank_candidate('管', candidates)['requires_review'])
        self.assertEqual(('', ''), classifier.classify_single('管', candidates))

    def test_missing_information_overrides_high_confidence(self):
        classifier = AIClassifier(api_key='test')
        classifier.client = _Client('{"code":"1","confidence":"high","missing_information":["VOC"]}')
        selected = classifier.rerank_candidate('喷漆', [{'code':'1', 'name':'涂料', 'is_leaf':True}], spec='红色', unit='瓶')
        self.assertTrue(selected['requires_review'])
        content = classifier.client.chat.completions.calls[0]['messages'][1]['content']
        self.assertIn('红色', content)
        self.assertIn('瓶', content)

    def test_non_object_json_and_empty_content_are_rejected(self):
        for content in ('[]', 'null', None, '', 'not json'):
            self.assertIsNone(AIClassifier._parse_json(content))

    def test_interpretation_only_returns_bounded_search_terms(self):
        classifier = AIClassifier(api_key='test')
        classifier.client = _Client('{"standard_name":"未知","search_terms":["a",12,"电缆","电缆","五金"],"confidence":"low","missing_information":["用途"]}')
        data = classifier.suggest_search_terms('简称')
        self.assertEqual(['电缆','五金'], data['search_terms'])
        self.assertTrue(data['needs_confirmation'])

    def test_rerank_accepts_only_leaf_candidate_from_candidate_list(self):
        classifier = AIClassifier(api_key="")
        classifier.client = _Client(
            '{"item":"钢扎带","code":"1090407040000000000","name":"AI改写名称","confidence":"high"}'
        )
        candidates = [
            {
                "code": "1090407040000000000",
                "name": "配电或电器控制设备",
                "category": "开关设备",
                "desc": "",
                "is_leaf": True,
                "source": "tax_list",
                "score": 10,
            }
        ]

        selected = classifier.rerank_candidate("钢扎带", candidates)

        self.assertIsNotNone(selected)
        self.assertEqual("1090407040000000000", selected["code"])
        self.assertEqual("配电或电器控制设备", selected["name"])
        self.assertEqual("ai_rerank", selected["source"])
        self.assertEqual("tax_list", selected["rule_source"])
        call = classifier.client.chat.completions.calls[0]
        self.assertEqual({"type": "json_object"}, call["response_format"])
        self.assertEqual({"thinking": {"type": "disabled"}}, call["extra_body"])

    def test_rerank_rejects_code_outside_candidates(self):
        classifier = AIClassifier(api_key="")
        classifier.client = _Client(
            '{"item":"钢扎带","code":"9999999999999999999","name":"不存在","confidence":"high"}'
        )
        candidates = [
            {
                "code": "1090407040000000000",
                "name": "配电或电器控制设备",
                "is_leaf": True,
                "source": "tax_list",
            }
        ]

        self.assertIsNone(classifier.rerank_candidate("钢扎带", candidates))

    def test_rerank_rejects_low_confidence(self):
        classifier = AIClassifier(api_key="")
        classifier.client = _Client(
            '{"item":"钢扎带","code":"1090407040000000000","name":"配电或电器控制设备","confidence":"low"}'
        )
        candidates = [
            {
                "code": "1090407040000000000",
                "name": "配电或电器控制设备",
                "is_leaf": True,
                "source": "tax_list",
            }
        ]

        self.assertIsNone(classifier.rerank_candidate("钢扎带", candidates))

    def test_rerank_rejects_missing_confidence(self):
        classifier = AIClassifier(api_key="")
        classifier.client = _Client(
            '{"item":"钢扎带","code":"1090407040000000000","name":"配电或电器控制设备"}'
        )
        candidates = [
            {
                "code": "1090407040000000000",
                "name": "配电或电器控制设备",
                "is_leaf": True,
                "source": "tax_list",
            }
        ]

        self.assertIsNone(classifier.rerank_candidate("钢扎带", candidates))


if __name__ == "__main__":
    unittest.main()
