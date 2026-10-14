"""非敏感的应用偏好与操作系统凭据存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .local_data import write_json
from .config import TAX_RATE

SERVICE_NAME = "FasterTax"
API_KEY_ACCOUNT = "deepseek-api-key"


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
        "ai_enabled": bool(values.get("ai_enabled", False)),
        "history_dir": str(values.get("history_dir", "") or ""),
        "industry": "hardware" if values.get("industry") == "hardware" else "",
        "tax_rate": str(values.get("tax_rate", TAX_RATE)),
        "price_mode": "exclusive" if values.get("price_mode") == "exclusive" else "inclusive",
    }


def save_settings(values: dict) -> None:
    write_json(settings_path(), {key: values[key] for key in (
        'ai_enabled', 'history_dir', 'industry', 'tax_rate', 'price_mode'
    ) if key in values})


def load_api_key() -> str:
    keyring = _keyring()
    return keyring.get_password(SERVICE_NAME, API_KEY_ACCOUNT) or ""


def save_api_key(api_key: str) -> None:
    _keyring().set_password(SERVICE_NAME, API_KEY_ACCOUNT, api_key)


def delete_api_key() -> None:
    keyring = _keyring()
    try:
        keyring.delete_password(SERVICE_NAME, API_KEY_ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


def _keyring():
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("安全保存密钥需要安装 keyring 依赖；也可以改用 DEEPSEEK_API_KEY 环境变量") from exc
    return keyring
