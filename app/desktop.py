"""pywebview 桌面窗口启动器。"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Thread

import webview

from app.api import DesktopAPI
from core.paths import WEB_DIR


def main() -> int:
    ui_dir = Path(WEB_DIR)
    api = DesktopAPI()
    window = webview.create_window(
        "发票明细导入助手",
        url=(ui_dir / "index.html").as_uri(),
        js_api=api,
        width=1320,
        height=860,
        min_size=(980, 640),
        text_select=True,
    )
    api._window = window
    closing_prepared = False
    closing_started = False
    def save_and_close():
        nonlocal closing_prepared
        try:
            values = window.evaluate_js("typeof ready !== 'undefined' && ready ? {text: document.querySelector('#manual-input').value, rows: allRows()} : null")
            if values:
                api.save_input(values['text'])
                api.update_items(values['rows'])
        except Exception:
            # 最后一次有效的原子草稿已保留；非法编辑不覆盖有效明细。
            pass
        finally:
            closing_prepared = True
            window.destroy()
    def save_before_close():
        nonlocal closing_started
        if closing_prepared:
            return True
        if closing_started:
            return False
        closing_started = True
        # 先取消本次关闭，再由后台线程读取页面；UI 线程不能等待 evaluate_js。
        Thread(target=save_and_close, daemon=True).start()
        return False
    window.events.closing += save_before_close
    webview.start(
        gui="edgechromium" if os.name == "nt" else None,
        debug=os.environ.get("FASTER_TAX_DEBUG") == "1",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
