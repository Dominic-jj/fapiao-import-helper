"""Windows onedir 构建；仅收集桌面端需要的资源与后端。"""
from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
datas = collect_data_files("webview")
datas += [
    (str(root / "app/web"), "app/web"),
    (str(root / "resources/templates/invoice_template.xlsx"), "resources/templates"),
    (str(root / "resources/reference/tax_list.xlsx"), "resources/reference"),
    (str(root / "resources/reference/hardware_terms.json"), "resources/reference"),
]
# 公共包只携带上述公共资源，历史与确认库由使用者在本机配置。

with_ai = os.environ.get("FASTER_TAX_BUILD_AI") == "1"
smoke = os.environ.get("FASTER_TAX_BUILD_SMOKE") == "1"
entry = root / ("tests/desktop_smoke.py" if smoke else "main.py")
name = "FapiaoImportHelperSmoke" if smoke else "FapiaoImportHelper"
excludes = [
    "streamlit", "pandas", "numpy", "scipy", "matplotlib", "IPython",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi", "cefpython3",
    "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa",
    "webview.platforms.cef", "webview.platforms.android", "tkinter",
]
if not with_ai:
    excludes.append("openai")

a = Analysis(
    [str(entry)], pathex=[str(root)], datas=datas,
    hiddenimports=["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"] + collect_submodules("keyring.backends"),
    excludes=excludes,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name=name,
    debug=False, strip=False, upx=False, console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=name)
