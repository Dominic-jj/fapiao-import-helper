"""真实 Windows WebView2 回归检查：python tests/desktop_smoke.py。"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import openpyxl
import webview

ROOT = Path(__file__).resolve().parents[1]
os.environ['LOCALAPPDATA'] = os.environ.get('FASTER_TAX_SMOKE_USER_DIR', str(ROOT / 'output' / 'desktop-smoke-user'))
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))

from app.desktop import main
from core.user_settings import save_settings
save_settings({'ai_enabled': False, 'industry': 'hardware', 'tax_rate': '0.01', 'price_mode': 'inclusive'})

os.environ["DEEPSEEK_API_KEY"] = ""
result = {}
output_dir = Path(os.environ.get("FASTER_TAX_SMOKE_OUTPUT", str(ROOT / "output")))
output_dir.mkdir(parents=True, exist_ok=True)
output = output_dir / "desktop-smoke.xlsx"
original_create = webview.create_window
original_start = webview.start


def create_hidden(*args, **kwargs):
    window = original_create(*args, **kwargs, hidden=True)
    window.create_file_dialog = lambda *args, **kwargs: (str(output),)
    return window


def check_window():
    window = webview.windows[0]

    def wait_for(expression):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if window.evaluate_js(expression):
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise AssertionError(f"Timed out: {expression}")

    try:
        wait_for("typeof ready !== 'undefined' && ready")
        text = json.dumps("漏电开关 个 1 65\nBV护套线 米 2 3", ensure_ascii=True)
        window.evaluate_js(f"document.querySelector('#manual-input').value = {text}; document.querySelector('#parse').click()")
        wait_for("document.querySelectorAll('tr[data-id]').length === 2 && pending === 0")
        window.evaluate_js("""
            const row = document.querySelector('tr[data-id]');
            const quantity = row.querySelector('[data-field=quantity]');
            quantity.focus(); quantity.value = '3';
            quantity.dispatchEvent(new Event('change', {bubbles:true}));
            row.querySelector('[data-field=spec]').focus();
        """)
        wait_for("pending === 0 && document.querySelector('.amount').textContent === '195.00'")
        assert window.evaluate_js("document.activeElement.dataset.field") == "spec"
        window.evaluate_js("document.querySelector('[data-action=suggest]').click()")
        wait_for("document.querySelector('.tax-results .candidate') && pending === 0")
        window.evaluate_js("""
            const candidates = document.querySelectorAll('.tax-results .candidate');
            candidates[candidates.length - 1].click();
        """)
        wait_for("pending === 0 && state.items[0].tax_match_source === 'manual'")
        code = window.evaluate_js("state.items[0].tax_code")
        window.evaluate_js("document.querySelector('#rematch').click()")
        wait_for("pending === 0")
        assert window.evaluate_js("state.items[0].tax_code") == code
        window.evaluate_js("document.querySelectorAll('[data-action=confirm-suggestion]')[0]?.click()")
        wait_for('pending === 0 && state.items.every(item => item.tax_confirmed)')
        # 未触发 change 的最后一个输入值，也必须在点击导出时被提交。
        window.evaluate_js("""
            const price = document.querySelector('[data-field=unit_price]');
            price.value = '7';
            price.dispatchEvent(new Event('change', {bubbles:true}));
            if (document.querySelector('#export').disabled) throw new Error('Edit disabled export before click');
            price.value = '8';
            document.querySelector('#export').click();
        """)
        wait_for("pending === 0 && document.querySelector('#notice').textContent.includes('.xlsx')")
        wb = openpyxl.load_workbook(output)
        try:
            assert wb["1-明细模板"]["G4"].value == 24
            assert wb["1-明细模板"]["B4"].value == code
        finally:
            wb.close()
        text = json.dumps('手喷漆 瓶 1 10', ensure_ascii=True)
        window.evaluate_js(f"document.querySelector('#manual-input').value = {text}; document.querySelector('#parse').click()")
        wait_for("pending === 0 && state.items.length === 1 && state.items[0].name === '手喷漆'")
        assert not window.evaluate_js('state.items[0].tax_code')
        assert 'VOC' in window.evaluate_js('document.querySelector(".current-tax").textContent')
        window.evaluate_js("document.querySelector('[data-action=suggest]').click()")
        wait_for('pending === 0 && document.querySelector(".tax-results .candidate")')
        assert window.evaluate_js('document.querySelectorAll(".tax-results .candidate").length') >= 2
        window.evaluate_js('document.querySelector(".tax-results .candidate").focus(); document.querySelector(".tax-results .candidate").dispatchEvent(new KeyboardEvent("keydown", {key:"Enter", bubbles:true}))')
        wait_for("pending === 0 && state.items[0].tax_match_source === 'manual'")
        # 完整税表：汇总项不可应用，按编码查询后可直接确认到当前行。
        window.evaluate_js("document.querySelector('[data-action=browse-tax]').click()")
        wait_for("document.querySelector('#tax-catalog').open && catalogPage && catalogPage.entry_count > 1000")
        window.evaluate_js("document.querySelector('#catalog-list .catalog-select').click()")
        wait_for("catalogSelected !== null")
        if not window.evaluate_js('catalogSelected.is_leaf'):
            assert window.evaluate_js("document.querySelector('#catalog-apply').disabled")
        target_code = window.evaluate_js('state.items[0].tax_code')
        window.evaluate_js(f"document.querySelector('#catalog-query').value = {json.dumps(target_code)}; document.querySelector('#catalog-search').click()")
        wait_for('catalogPage.total === 1')
        window.evaluate_js("document.querySelector('#catalog-list .catalog-select').click()")
        wait_for('catalogSelected !== null && catalogSelected.is_leaf')
        assert window.evaluate_js("document.querySelector('#catalog-description').textContent.length > 0")
        assert window.evaluate_js("document.querySelector('#catalog-detail-path').textContent.length > 0")
        rect = window.evaluate_js("(() => { const r = document.querySelector('#tax-catalog').getBoundingClientRect(); return {left:r.left, right:r.right, width:innerWidth}; })()")
        assert rect['left'] >= 0 and rect['right'] <= rect['width']
        window.evaluate_js("document.querySelector('#catalog-apply').click()")
        wait_for("pending === 0 && !document.querySelector('#tax-catalog').open")
        assert window.evaluate_js('state.items[0].tax_code') == target_code
        assert window.evaluate_js('state.items[0].tax_confirmed')
        result['full_tax_catalog'] = True
        result.update(ok=True, focus_preserved=True, manual_tax_preserved=True, latest_edit_exported=True, uncertain_product_review=True)
    except Exception as exc:
        result.update(ok=False, error=str(exc))
        try:
            result['notice'] = window.evaluate_js('document.querySelector("#notice").textContent')
        except Exception:
            pass
    finally:
        window.destroy()


def start_checked(**kwargs):
    return original_start(check_window, **kwargs)


with patch("webview.create_window", create_hidden), patch("webview.start", start_checked):
    main()
print(json.dumps(result, ensure_ascii=True))
(output_dir / "desktop-smoke.json").write_text(json.dumps(result), encoding="utf-8")
raise SystemExit(0 if result.get("ok") else 1)
