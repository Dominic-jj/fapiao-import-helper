import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.paths import INVOICE_TEMPLATE_PATH, TAX_LIST_PATH, TRAIN_DATA_DIR, USER_DATA_DIR  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_default_paths_resolve_new_data_layout(self):
        self.assertEqual(str(ROOT / "resources" / "reference" / "tax_list.xlsx"), TAX_LIST_PATH)
        self.assertEqual(str(ROOT / "resources" / "templates" / "invoice_template.xlsx"), INVOICE_TEMPLATE_PATH)
        self.assertEqual(str(Path(USER_DATA_DIR) / "resources" / "reference" / "train_data"), TRAIN_DATA_DIR)
        self.assertTrue(os.path.exists(TAX_LIST_PATH))
        self.assertTrue(os.path.exists(INVOICE_TEMPLATE_PATH))


if __name__ == "__main__":
    unittest.main()
