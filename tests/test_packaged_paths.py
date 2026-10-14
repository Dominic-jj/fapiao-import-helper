import importlib.util
import sys
from pathlib import Path

from core import paths


def test_frozen_resources_and_persistent_mappings(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    local = tmp_path / "local"
    (bundle / "resources/mappings").mkdir(parents=True)
    (bundle / "resources/mappings/tax_aliases.json").write_text('{"真实商品":"123"}', encoding="utf-8")
    (bundle / "resources/mappings/confirmed_tax_codes.example.json").write_text('{"示例":"999"}', encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    spec = importlib.util.spec_from_file_location("test_frozen_paths", paths.__file__)
    frozen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen)
    frozen.ensure_user_resources()
    assert Path(frozen.INVOICE_TEMPLATE_PATH) == bundle / "resources/templates/invoice_template.xlsx"
    assert Path(frozen.WEB_DIR) == bundle / "app/web"
    assert Path(frozen.BUNDLED_TRAIN_DATA_DIR) != Path(frozen.TRAIN_DATA_DIR)
    assert not Path(frozen.TAX_ALIASES_PATH).exists()
    assert not Path(frozen.CONFIRMED_TAX_CODES_PATH).exists()
    Path(frozen.TAX_ALIASES_PATH).write_text("{}", encoding="utf-8")
    frozen.ensure_user_resources()
    assert Path(frozen.TAX_ALIASES_PATH).read_text(encoding="utf-8") == "{}"
