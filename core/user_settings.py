"""本地应用偏好存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .local_data import write_json
from .config import TAX_RATE


def settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "FasterTax" / "settings.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "faster-tax" / "settings.json"


def load_settings() -> dict:
    path = settings_path()
    try:
        with path.open("r", encoding="utf-8") as file:
            values = json.load(file)
    except (OSError, json.JSONDecodeError):
        values = {}
    if not isinstance(values, dict):
        values = {}
    return {
        "history_dir": str(values.get("history_dir", "") or ""),
        "industry": "hardware" if values.get("industry") == "hardware" else "",
        "tax_rate": str(values.get("tax_rate", TAX_RATE)),
        "price_mode": "exclusive" if values.get("price_mode") == "exclusive" else "inclusive",
    }


def save_settings(values: dict) -> None:
    write_json(settings_path(), {key: values[key] for key in (
        'history_dir', 'industry', 'tax_rate', 'price_mode'
    ) if key in values})
