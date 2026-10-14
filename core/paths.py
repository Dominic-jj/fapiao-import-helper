"""项目路径配置。"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


if getattr(sys, "frozen", False):
    # PyInstaller places bundled, read-only assets under _MEIPASS.
    PROJECT_ROOT = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_LOCAL_APP_DATA = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.local/share")
USER_DATA_DIR = os.path.join(_LOCAL_APP_DATA, "FasterTax")

RESOURCES_DIR = os.path.join(PROJECT_ROOT, "resources")
USER_RESOURCES_DIR = os.path.join(USER_DATA_DIR, "resources")

TAX_LIST_PATH = os.path.join(RESOURCES_DIR, "reference", "tax_list.xlsx")
HARDWARE_TERMS_PATH = os.path.join(RESOURCES_DIR, "reference", "hardware_terms.json")
INVOICE_TEMPLATE_PATH = os.path.join(RESOURCES_DIR, "templates", "invoice_template.xlsx")
BUNDLED_TRAIN_DATA_DIR = os.path.join(RESOURCES_DIR, "reference", "train_data")
WEB_DIR = os.path.join(PROJECT_ROOT, "app", "web")
TRAIN_DATA_DIR = os.path.join(USER_RESOURCES_DIR, "reference", "train_data")
MAPPINGS_DIR = os.path.join(USER_RESOURCES_DIR, "mappings")
TAX_ALIASES_PATH = os.path.join(MAPPINGS_DIR, "tax_aliases.json")
CONFIRMED_TAX_CODES_PATH = os.path.join(MAPPINGS_DIR, "confirmed_tax_codes.json")


def ensure_user_resources() -> None:
    """创建可写目录；源码旧映射只在首次迁移时复制，原文件保留。"""
    os.makedirs(TRAIN_DATA_DIR, exist_ok=True)
    os.makedirs(MAPPINGS_DIR, exist_ok=True)
    if getattr(sys, 'frozen', False):
        # 公共安装包不能导入内置的个人确认；既有用户目录仍保持原位。
        return
    for filename in ("tax_aliases.json", "confirmed_tax_codes.json"):
        source = Path(RESOURCES_DIR, "mappings", filename)
        destination = Path(MAPPINGS_DIR, filename)
        if source.is_file() and not destination.exists():
            shutil.copyfile(source, destination)
