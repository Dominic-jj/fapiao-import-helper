"""pytest/unittest 发现测试时保证项目根目录可导入。"""

import sys
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    # 任何测试不得读写真实用户草稿、偏好或系统凭据。
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'user-data'))
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'user-data'))
    monkeypatch.setattr('app.api.load_api_key', lambda: '')
    monkeypatch.setattr('app.api.ensure_user_resources', lambda: None)
