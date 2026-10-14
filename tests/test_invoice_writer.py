import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import openpyxl


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.invoice_writer import generate  # noqa: E402
from core.models import Item  # noqa: E402


class InvoiceWriterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.template_path = self.temp_dir / "invoice_template.xlsx"
        self.output_path = self.temp_dir / "output.xlsx"
        self._write_template()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def _write_template(self):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "1-明细模板"
        ws.append(["说明"])
        ws.append(["说明"])
        ws.append(["项目名称", "税收分类编码", "规格型号", "单位", "数量", "单价", "金额", "税率"])
        wb.save(self.template_path)
        wb.close()

    def test_generate_writes_items_to_template(self):
        generate(
            [
                Item(
                    name="漏电开关",
                    spec="2x63A",
                    unit="个",
                    quantity=2,
                    unit_price=65,
                    amount=130,
                    tax_code="1090407040000000000",
                    tax_name="配电或电器控制设备",
                )
            ],
            str(self.output_path),
            template_path=str(self.template_path),
        )

        wb = openpyxl.load_workbook(self.output_path, data_only=True)
        ws = wb["1-明细模板"]

        self.assertEqual("漏电开关", ws["A4"].value)
        self.assertEqual("1090407040000000000", ws["B4"].value)
        self.assertEqual("@", ws["B4"].number_format)
        self.assertEqual("2x63A", ws["C4"].value)
        self.assertEqual("个", ws["D4"].value)
        self.assertEqual(2, ws["E4"].value)
        self.assertEqual(65, ws["F4"].value)
        self.assertEqual(130, ws["G4"].value)
        self.assertEqual("0.01", ws["H4"].value)

        wb.close()

    def _read_detail_sheet(self):
        wb = openpyxl.load_workbook(self.output_path, data_only=True)
        return wb["1-明细模板"], wb

    def test_existing_optional_columns_and_formula_like_text_are_safe(self):
        wb = openpyxl.load_workbook(self.template_path)
        ws = wb["1-明细模板"]
        ws["I4"], ws["J4"], ws["K4"] = 99, "旧优惠", "旧煤炭"
        wb.create_sheet("其他说明")["A1"] = "保留"
        wb.save(self.template_path)
        wb.close()
        generate([Item("=1+1", "=A1", "个", 1, 2, 2)], str(self.output_path), str(self.template_path))
        wb = openpyxl.load_workbook(self.output_path, data_only=False)
        try:
            ws = wb["1-明细模板"]
            self.assertEqual("s", ws["A4"].data_type)
            self.assertEqual("=1+1", ws["A4"].value)
            self.assertTrue(all(ws[f"{col}4"].value is None for col in "IJK"))
            self.assertEqual("保留", wb["其他说明"]["A1"].value)
        finally:
            wb.close()

    def test_amount_is_recomputed_on_write(self):
        # 防止页面传入陈旧的 amount 字段，导出时统一按数量 x 单价重算并取整。
        generate(
            [
                Item(
                    name="灯管",
                    spec="",
                    unit="支",
                    quantity=3,
                    unit_price=0.1,
                    amount=999,
                    tax_code="1090407040000000000",
                )
            ],
            str(self.output_path),
            template_path=str(self.template_path),
        )

        ws, wb = self._read_detail_sheet()
        self.assertEqual(0.3, ws["G4"].value)
        wb.close()

    def test_leftover_rows_below_items_are_cleared(self):
        # 模板里预填了示例行，但明细只有 1 行时不应把示例行一并交出去。
        wb = openpyxl.load_workbook(self.template_path)
        ws = wb["1-明细模板"]
        for row in range(4, 9):
            ws[f"A{row}"] = f"示例物品{row}"
        wb.save(self.template_path)
        wb.close()

        generate(
            [
                Item(
                    name="漏电开关",
                    spec="",
                    unit="个",
                    quantity=1,
                    unit_price=65,
                    amount=65,
                    tax_code="1090407040000000000",
                )
            ],
            str(self.output_path),
            template_path=str(self.template_path),
        )

        ws, wb = self._read_detail_sheet()
        self.assertEqual("漏电开关", ws["A4"].value)
        self.assertEqual(4, ws.max_row)
        wb.close()


if __name__ == "__main__":
    unittest.main()
