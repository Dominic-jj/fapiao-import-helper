import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.parser import parse_text_block, parse_text_line  # noqa: E402


class ParserUnitTest(unittest.TestCase):
    def test_unit_is_not_limited_by_whitelist(self):
        item = parse_text_line("16# 铁线 斤 2.5 6")

        self.assertIsNotNone(item)
        self.assertEqual("16#", item.spec)
        self.assertEqual("铁线", item.name)
        self.assertEqual("斤", item.unit)
        self.assertEqual(2.5, item.quantity)
        self.assertEqual(6, item.unit_price)
        self.assertEqual(15, item.amount)

    def test_thousands_separator_is_not_treated_as_csv(self):
        item = parse_text_line("电缆 米 1,000 3.5")

        self.assertIsNotNone(item)
        self.assertEqual("电缆", item.name)
        self.assertEqual("米", item.unit)
        self.assertEqual(1000, item.quantity)
        self.assertEqual(3500.0, item.amount)

    def test_amount_is_rounded_to_money_precision(self):
        items, errors = parse_text_block("灯管 支 3 0.1")

        self.assertEqual([], errors)
        self.assertEqual(0.3, items[0].amount)

    def test_pipe_inch_spec_is_recognized(self):
        # 4分 / 6分 / 1寸 等英制管径规格应作为规格提取。
        for spec in ("4分", "6分", "1.5寸"):
            item = parse_text_line(f"{spec} 水表 个 4 95")

            self.assertIsNotNone(item)
            self.assertEqual(spec, item.spec)
            self.assertEqual("水表", item.name)
            self.assertEqual("个", item.unit)
            self.assertEqual(4, item.quantity)
            self.assertEqual(95, item.unit_price)
            self.assertEqual(380, item.amount)

    def test_cable_core_spec_is_recognized(self):
        # 12芯 / 2芯 / 24芯 等线缆芯数应作为规格提取，而不是并入名称。
        for spec in ("12芯", "2芯", "24芯"):
            item = parse_text_line(f"{spec} 室外光缆 米 100 5")

            self.assertIsNotNone(item)
            self.assertEqual(spec, item.spec)
            self.assertEqual("室外光缆", item.name)
            self.assertEqual("米", item.unit)
            self.assertEqual(100, item.quantity)
            self.assertEqual(5, item.unit_price)
            self.assertEqual(500, item.amount)

    def test_cable_category_spec_is_recognized(self):
        # 6类 / 超五类 等网线类别应作为规格提取。
        item = parse_text_line("6类 网线 箱 2 300")

        self.assertIsNotNone(item)
        self.assertEqual("6类", item.spec)
        self.assertEqual("网线", item.name)
        self.assertEqual("箱", item.unit)
        self.assertEqual(600, item.amount)

    def test_multi_word_name_with_spec_is_kept_together(self):
        # 多个空格分隔词中仅首个是规格时，后词应合并为名称。
        item = parse_text_line("12芯 室外 光缆 米 100 5")

        self.assertIsNotNone(item)
        self.assertEqual("12芯", item.spec)
        self.assertEqual("室外 光缆", item.name)
        self.assertEqual("米", item.unit)

    def test_cm_shorthand_spec_is_recognized(self):
        # 五金常见“X厘”= X 毫米（如 10厘 / 12厘 套筒头），应作为规格提取。
        for spec in ("10厘", "12厘"):
            item = parse_text_line(f"{spec} 套筒头 个 8 12")

            self.assertIsNotNone(item)
            self.assertEqual(spec, item.spec)
            self.assertEqual("套筒头", item.name)
            self.assertEqual("个", item.unit)

    def test_common_hardware_measure_shorthands_are_specs(self):
        # 10方(电线截面)、2.5平、6号(螺丝) 等五金规格简写应识别为规格。
        cases = {
            "10方": "电线",
            "2.5平": "电线",
            "6号": "螺丝",
        }
        for spec, name in cases.items():
            item = parse_text_line(f"{spec} {name} 米 1 100")

            self.assertIsNotNone(item)
            self.assertEqual(spec, item.spec)
            self.assertEqual(name, item.name)

    def test_number_plus_measure_word_in_middle_is_not_split(self):
        # 数字+量词若位于名称中间（无空格分词），不应被误拆。
        item = parse_text_line("3号电池 盒 1 20")

        self.assertIsNotNone(item)
        self.assertEqual("", item.spec)
        self.assertEqual("3号电池", item.name)


if __name__ == "__main__":
    unittest.main()
