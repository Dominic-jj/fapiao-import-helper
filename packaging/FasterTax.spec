"""Windows 单文件构建；公共资源内置，输出一个可直接运行的 exe。"""
from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
icon_path = root / "resources/icons/fapiao-import-helper.ico"
datas = collect_data_files("webview")
datas += [
    (str(root / "app/web"), "app/web"),
    (str(root / "resources/templates/invoice_template.xlsx"), "resources/templates"),
    (str(root / "resources/reference/tax_list.xlsx"), "resources/reference"),
    (str(root / "resources/reference/hardware_terms.json"), "resources/reference"),
    (str(root / "LICENSE"), "."),
]
# 公共包只携带上述公共资源，历史与确认库由使用者在本机配置。

smoke = os.environ.get("FASTER_TAX_BUILD_SMOKE") == "1"
entry = root / ("tests/desktop_smoke.py" if smoke else "main.py")
name = "FapiaoImportHelperSmoke" if smoke else "FapiaoImportHelper"
excludes = [
    "streamlit", "pandas", "numpy", "scipy", "matplotlib", "IPython",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy", "gi", "cefpython3",
    "webview.platforms.qt", "webview.platforms.gtk", "webview.platforms.cocoa",
    "webview.platforms.cef", "webview.platforms.android", "tkinter",
]

a = Analysis(
    [str(entry)], pathex=[str(root)], datas=datas,
    hiddenimports=["webview.platforms.winforms", "webview.platforms.edgechromium", "clr"],
    excludes=excludes,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name=name,
    debug=False, strip=False, upx=False, console=False,
    icon=str(icon_path),
)
