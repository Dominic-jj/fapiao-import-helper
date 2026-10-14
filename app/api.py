"""桌面 UI 的 Python API，集中维护明细状态和导出校验。"""

from __future__ import annotations

from dataclasses import replace, fields
from decimal import Decimal, InvalidOperation
from datetime import datetime
from functools import wraps
from inspect import signature
from pathlib import Path
from threading import RLock
from threading import Event
import os
import shutil
import hashlib

from app.matching import match_items_with_ai
from core.ai_classifier import AIClassifier
from core.invoice_writer import generate
from core.models import Item, compute_amount
from core.parser import parse_text_block
from core.paths import ensure_user_resources
from core.paths import TRAIN_DATA_DIR
from core.local_data import read_json, write_json
from core.tax_matcher import TaxMatcher
from core.tax_catalog import TaxCatalog
from core.user_settings import delete_api_key, load_api_key, load_settings, save_api_key, save_settings
from core.user_settings import settings_path
from core.validators import to_float, validate_item


def synchronized(method):
    """pywebview 在独立线程执行调用，状态变更必须串行。"""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            result = method(self, *args, **kwargs)
            if method.__name__ in {'parse_text', 'update_items', 'add_item', 'remove_item', 'clear_items',
                                   'select_tax', 'rematch', 'save_input', 'configure_products'}:
                self._save_draft()
                if method.__name__ != 'save_input':
                    self._revision += 1
                if isinstance(result, dict):
                    result['draft_message'] = self._draft_message
                    if 'items' in result:
                        result['revision'] = self._revision
                    if 'state' in result:
                        result['state']['revision'] = self._revision
            return result
    # pywebview 用 getfullargspec 生成桥接函数，必须保留装饰前的参数列表。
    call.__signature__ = signature(method)
    return call


class DesktopAPI:
    def __init__(self, draft_path: str | None = None) -> None:
        self._lock = RLock()
        ensure_user_resources()
        self._settings = load_settings()
        self._matcher = TaxMatcher()
        self._matcher.industry = self._settings.get('industry', '')
        history_dir = self._settings.get('history_dir', '')
        if history_dir:
            self._matcher = TaxMatcher(train_dir=history_dir, industry=self._matcher.industry)
        self._ai_enabled = self._settings["ai_enabled"]
        try:
            self._saved_api_key = load_api_key()
            self._credential_error = ""
        except Exception as exc:
            self._saved_api_key = ""
            self._credential_error = str(exc)
        self._ai_classifier = AIClassifier(api_key=self._saved_api_key or None)
        self._items: list[Item] = []
        self._parse_errors: list[dict] = []
        self._match_stats: dict | None = None
        self._next_id = 0
        self._window = None
        self._revision = 0
        self._tax_fingerprint = hashlib.sha256(Path(self._matcher.tax_list_path).read_bytes()).hexdigest()
        self._raw_text = ''
        self._draft_path = Path(draft_path) if draft_path else settings_path().with_name('draft.json')
        self._draft_message = ''
        self._draft_corrupt = False
        self._ai_jobs: dict[int, Event] = {}
        self._ai_cache: dict[tuple, Item] = {}
        self._ai_inflight: dict[tuple, dict] = {}
        self._ai_generation = 0
        self._tax_catalog = None
        self._restore_draft()

    def _restore_draft(self) -> None:
        try:
            data = read_json(self._draft_path)
            if not data:
                return
            if data.get('version') != 1 or not isinstance(data.get('items'), list):
                raise ValueError('不支持的草稿格式')
            restored = []
            allowed = {field.name for field in fields(Item)}
            for value in data['items']:
                item = Item(**{key: val for key, val in value.items() if key in allowed})
                if any(not isinstance(getattr(item, field), str) for field in ('name', 'spec', 'unit', 'tax_code')):
                    raise ValueError('草稿商品字段无效')
                if any(to_float(value) is None or to_float(value) < 0 for value in (item.quantity, item.unit_price)) or not isinstance(item.row_id, int) or item.row_id <= 0:
                    raise ValueError('草稿中存在无效明细')
                item.quantity, item.unit_price = to_float(item.quantity), to_float(item.unit_price)
                item.amount = compute_amount(item.quantity, item.unit_price)
                if to_float(item.amount) is None:
                    raise ValueError('草稿金额超出范围')
                item.tax_confirmed = item.tax_confirmed is True
                if data.get('tax_fingerprint') != self._tax_fingerprint:
                    item.tax_confirmed = False
                    item.tax_review_reason = '税表发生变化，请重新核对分类'
                if not self._matcher.is_leaf_code(item.tax_code):
                    item.tax_code = item.tax_name = ''
                    item.tax_confirmed = False
                elif item.tax_code:
                    item.tax_name = self._matcher.get_entry(item.tax_code)['name']
                restored.append(item)
            if len({item.row_id for item in restored}) != len(restored):
                raise ValueError('草稿行标识重复')
            self._items = restored
            self._next_id = max((item.row_id for item in restored), default=0)
            self._raw_text = str(data.get('raw_text', ''))
            errors = data.get('parse_errors', [])
            if not isinstance(errors, list) or any(not isinstance(e, dict) or not {'line_number', 'raw', 'reason'} <= e.keys() for e in errors):
                raise ValueError('草稿解析错误信息无效')
            self._parse_errors = errors
            self._draft_message = '已恢复上次草稿'
        except Exception as exc:
            self._items, self._parse_errors = [], []
            self._draft_corrupt = True
            self._draft_message = f'草稿无法读取，原文件已保留：{exc}'

    def _save_draft(self) -> None:
        try:
            if self._draft_corrupt and self._draft_path.exists():
                backup = self._draft_path.with_name('draft-corrupt-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.json')
                shutil.copyfile(self._draft_path, backup)
                self._draft_corrupt = False
            write_json(self._draft_path, {'version': 1, 'raw_text': self._raw_text,
                'items': [item.to_dict() for item in self._items], 'parse_errors': self._parse_errors,
                'tax_fingerprint': self._tax_fingerprint})
            self._draft_message = '草稿已自动保存'
        except Exception as exc:
            self._draft_message = f'草稿保存失败，上次文件保留：{exc}'

    @synchronized
    def save_input(self, text: str) -> dict:
        self._raw_text = str(text or '')
        return {'ok': True}

    @synchronized
    def get_state(self) -> dict:
        items = []
        for item in self._items:
            item_state = item.to_dict()
            entry = self._matcher.get_entry(item.tax_code) if item.tax_code else None
            item_state["tax_category"] = (entry or {}).get("category", "")
            items.append(item_state)
        if not self._ai_enabled:
            ai_message = "AI 辅助已关闭；本地匹配和手动选择仍可使用"
        elif not self._ai_classifier.is_available():
            ai_message = self._ai_classifier.unavailable_reason
        else:
            ai_message = "AI 辅助已开启"
        return {
            'revision': self._revision,
            "items": items,
            "parse_errors": [dict(error) for error in self._parse_errors],
            "match_stats": dict(self._match_stats) if self._match_stats else None,
            "ai_available": self._ai_enabled and self._ai_classifier.is_available(),
            "ai_message": ai_message,
            "raw_text": self._raw_text,
            "draft_message": self._draft_message,
            "product_settings": {
                'history_dir': self._settings.get('history_dir', '') or TRAIN_DATA_DIR,
                'industry': self._settings.get('industry', ''),
                'tax_rate': self._settings.get('tax_rate', '0.01'),
                'price_mode': self._settings.get('price_mode', 'inclusive'),
                'history_stats': dict(self._matcher.history_stats),
            },
            "ai_settings": {
                "enabled": self._ai_enabled,
                "available": self._ai_classifier.is_available(),
                "key_configured": bool(self._ai_classifier.api_key),
                "key_source": "系统凭据管理器" if self._saved_api_key else ("环境变量" if self._ai_classifier.api_key else "未配置"),
                "message": self._credential_error or ai_message,
            },
        }

    @synchronized
    def configure_ai(self, enabled: bool, api_key: str = "", clear_saved_key: bool = False) -> dict:
        """保存 AI 开关和可选密钥；密钥只写入操作系统凭据管理器。"""
        new_key = str(api_key or "").strip()
        try:
            if new_key:
                save_api_key(new_key)
                self._saved_api_key = new_key
                self._ai_classifier.update_api_key(new_key)
                self._credential_error = ""
            elif clear_saved_key:
                delete_api_key()
                self._saved_api_key = ""
                self._ai_classifier.update_api_key(None)
                self._credential_error = ""
            self._settings["ai_enabled"] = bool(enabled)
            save_settings(self._settings)
        except Exception as exc:
            return {"ok": False, "message": str(exc), "state": self.get_state()}
        self._ai_enabled = bool(enabled)
        for event in self._ai_jobs.values():
            event.set()
        self._ai_cache.clear()
        self._ai_generation += 1
        self._match_stats = None
        return {"ok": True, "state": self.get_state()}

    @synchronized
    def parse_text(self, text: str) -> dict:
        self._raw_text = str(text or '')
        self._match_stats = None
        self._items, errors = parse_text_block(str(text or ""))
        self._parse_errors = [
            {"line_number": error.line_number, "raw": error.raw, "reason": error.reason}
            for error in errors
        ]
        for item in self._items:
            self._next_id += 1
            item.row_id = self._next_id
            item.tax_rate = self._settings.get('tax_rate', '0.01')
        self._match_items(self._items)
        return self.get_state()

    @synchronized
    def update_item(self, row_id: int, values: dict) -> dict:
        return self.update_items([{**values, "row_id": row_id}])

    @synchronized
    def update_items(self, rows: list[dict]) -> dict:
        # 完整解析后才提交，非法数字不能改成 0，批量提交不能只更新一部分。
        updates = {}
        pending = []
        for values in rows:
            original = self._item(values["row_id"])
            item = replace(original)
            for field in ("name", "spec", "unit"):
                setattr(item, field, str(values.get(field, getattr(item, field)) or "").strip())
            for field, label in (("quantity", "数量"), ("unit_price", "单价")):
                number = to_float(values.get(field, getattr(item, field)))
                if number is None or number < 0:
                    raise ValueError(f"第 {item.row_id} 行：{label}必须是非负有限数字")
                setattr(item, field, number)
            if 'tax_rate' in values:
                item.tax_rate = self._rate(values['tax_rate'])
            item.amount = compute_amount(item.quantity, item.unit_price)
            if to_float(item.amount) is None:
                raise ValueError(f"第 {item.row_id} 行：计算金额超出有效范围")
            if item.name != original.name:
                item.tax_code = item.tax_name = item.tax_match_source = ""
                item.tax_ai_confidence = ""
                item.tax_review_reason = item.tax_standard_name = item.tax_match_confidence = ""
                item.tax_confirmed = False
            context_changed = item.spec != original.spec or item.unit != original.unit
            if context_changed and item.tax_match_source == 'manual' and self._matcher.context_key(item.spec, item.unit) != self._matcher.context_key(original.spec, original.unit):
                item.tax_review_reason = '规格或单位已变化，请核对保留的人工分类'
                item.tax_confirmed = False
            if item.name and (item.name != original.name or
                              (context_changed and item.tax_match_source != 'manual')):
                pending.append(item)
            updates[item.row_id] = item
        self._match_items(pending)
        self._items = [updates.get(item.row_id, item) for item in self._items]
        return self.get_state()

    @synchronized
    def add_item(self) -> dict:
        self._next_id += 1
        self._items.append(Item("", "", "", 0, 0, 0, row_id=self._next_id, tax_rate=self._settings.get('tax_rate', '0.01')))
        return self.get_state()

    @synchronized
    def remove_item(self, row_id: int) -> dict:
        self._items = [item for item in self._items if item.row_id != int(row_id)]
        return self.get_state()

    @synchronized
    def clear_items(self) -> dict:
        self._raw_text = ''
        self._items = []
        self._parse_errors = []
        self._match_stats = None
        return self.get_state()

    @synchronized
    def rematch(self) -> dict:
        self._match_stats = None
        pending = [item for item in self._items if item.tax_match_source != "manual"]
        for item in pending:
            item.tax_code = item.tax_name = item.tax_match_source = ""
            item.tax_ai_confidence = ""
        self._match_items(pending)
        return self.get_state()

    @synchronized
    def search_tax(self, query: str, spec: str = '', unit: str = '', limit: int = 35) -> list[dict]:
        query = str(query or "").strip()
        if not query:
            return []
        # 搜索必须能跳出已有历史映射，支持名称、简称和编码。
        direct = []
        normalized = query.casefold()
        for entry in self._matcher.entries:
            text = f'{entry["code"]} {entry["name"]} {entry.get("category", "")} {entry.get("desc", "")}'
            if entry.get("is_leaf", False) and normalized in text.casefold():
                direct.append({**entry, "score": 0})
        candidates = self._matcher.match_candidates(query, top_n=35, spec=spec, unit=unit)
        # 商品解释候选优先，冲突的旧记录放后面，避免默认选中已知错配。
        preferred = [entry for entry in candidates if entry.get('source', '').startswith(('confirmed', 'history')) and not entry.get('requires_review')]
        preferred += [entry for entry in candidates if entry.get('source') == 'hardware_rule']
        direct.sort(key=lambda e: (e['code'] != query, e['name'] != query, len(e['name'])))
        ordered = {}
        for entry in preferred + direct + candidates:
            ordered.setdefault(entry['code'], entry)
        candidates = list(ordered.values())
        return [self._candidate_payload(entry) for entry in candidates[:max(1, min(int(limit), 200))]]

    @synchronized
    def select_tax(self, row_id: int, code: str) -> dict:
        item = self._item(row_id)
        code = self._matcher.normalize_code(code)
        valid, message = self._matcher.validate_tax_code(code)
        if not valid:
            return {"ok": False, "message": message, "state": self.get_state()}
        entry = self._matcher.get_entry(code) or {}
        item.tax_code = code
        item.tax_name = entry.get("name", "")
        item.tax_match_source = "manual"
        item.tax_ai_confidence = ""
        item.tax_match_confidence = "high"
        item.tax_review_reason = ""
        item.tax_confirmed = True
        return {"ok": True, "state": self.get_state()}

    def _catalog(self) -> TaxCatalog:
        if self._tax_catalog is None:
            self._tax_catalog = TaxCatalog(self._matcher.entries)
        return self._tax_catalog

    @synchronized
    def browse_tax_catalog(self, query: str = '', parent_code: str = '', offset: int = 0,
                           page_size: int = 60, leaf_only: bool = False) -> dict:
        return self._catalog().browse(query, parent_code, offset, page_size, leaf_only)

    @synchronized
    def tax_catalog_detail(self, code: str) -> dict:
        return self._catalog().detail(code)

    @synchronized
    def save_confirmations(self) -> dict:
        saved, errors = 0, []
        codes_by_name = {}
        for item in self._items:
            if item.name and item.tax_code:
                codes_by_name.setdefault((item.name, self._matcher.context_key(item.spec, item.unit)), set()).add(item.tax_code)
        conflicts = {name for name, codes in codes_by_name.items() if len(codes) > 1}
        errors.extend(f"{key[0]}：同名同属性明细选择了不同税编，请统一后保存" for key in sorted(conflicts))
        seen = set(conflicts)
        for item in self._items:
            key = (item.name, self._matcher.context_key(item.spec, item.unit))
            if not item.name or not item.tax_code or key in seen:
                continue
            if not item.tax_confirmed:
                errors.append(f'{item.name}：请先确认税编建议')
                continue
            seen.add(key)
            ok, message = self._matcher.save_confirmed_tax_code(item.name, item.tax_code, item.tax_name, item.spec, item.unit)
            if ok:
                saved += 1
            else:
                errors.append(f"{item.name}：{message}")
        return {"saved": saved, "errors": errors}

    @synchronized
    def export_invoice(self) -> dict:
        errors = self._validation_errors()
        if errors:
            return {"ok": False, "message": "\n".join(errors)}
        if not self._items:
            return {"ok": False, "message": "请先录入明细"}
        if not self._window:
            return {"ok": False, "message": "桌面窗口尚未就绪"}

        import webview

        filename = f"发票明细_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
        try:
            paths = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                save_filename=filename,
                file_types=("Excel 文件 (*.xlsx)",),
            )
            if not paths:
                return {"ok": False, "cancelled": True}
            output_path = Path(paths[0])
            if output_path.suffix.lower() != ".xlsx":
                output_path = output_path.with_suffix(".xlsx")
            generate(self._items, str(output_path))
        except Exception as exc:
            return {"ok": False, "message": f"生成失败：{exc}"}
        return {"ok": True, "path": str(output_path)}

    def _match_items(self, items: list[Item]) -> None:
        pending = [item for item in items if item.name]
        if pending:
            # 录入始终本地完成，AI 只通过逐行按需接口执行。
            self._match_stats = match_items_with_ai(pending, self._matcher, None)
            if self._ai_enabled and self._ai_classifier.is_available():
                self._match_stats['ai_available'] = True
                self._match_stats['ai_skip_reason'] = '本轮本地匹配，AI 可按需使用'

    def _validation_errors(self) -> list[str]:
        errors = [f'输入第 {error["line_number"]} 行未解析，请修正后重新解析' for error in self._parse_errors]
        for item in self._items:
            errors.extend(validate_item(item))
            valid, message = self._matcher.validate_tax_code(item.tax_code)
            if not valid:
                errors.append(f"第 {item.row_id} 行：{message}")
            elif not item.tax_confirmed:
                errors.append(f'第 {item.row_id} 行：税编建议尚未确认')
            try:
                self._rate(item.tax_rate or self._settings.get('tax_rate', '0.01'))
            except ValueError as exc:
                errors.append(f'第 {item.row_id} 行：{exc}')
        return errors

    def _candidate_payload(self, entry: dict) -> dict:
        name, category = entry.get("name", ""), entry.get("category", "")
        return {
            "code": entry.get("code", ""), "name": name, "category": category,
            "display": f"{name}（{category}）" if category and category != name else name,
            "score": round(float(entry.get("score", 0) or 0), 2),
            "requires_review": bool(entry.get('requires_review')),
            "review_reason": entry.get('review_reason', ''),
            "standard_name": entry.get('standard_name', ''),
            'desc': entry.get('desc', ''),
            'source': entry.get('source', 'tax_list'),
        }

    @staticmethod
    def _rate(value) -> str:
        try:
            rate = Decimal(str(value))
            if not rate.is_finite() or rate < 0 or rate > 1:
                raise ValueError('税率须为 0 到 1 的有限数值')
            return format(rate, 'f')
        except (InvalidOperation, TypeError):
            raise ValueError('税率须为 0 到 1 的有限数值') from None

    @synchronized
    def configure_products(self, history_dir: str, industry: str, tax_rate: str, price_mode: str) -> dict:
        directory = str(history_dir or '').strip()
        if directory and not Path(directory).is_dir():
            return {'ok': False, 'message': '历史目录不存在，原设置保留'}
        settings = {**self._settings, 'history_dir': directory, 'industry': 'hardware' if industry == 'hardware' else '',
                    'tax_rate': self._rate(tax_rate), 'price_mode': 'exclusive' if price_mode == 'exclusive' else 'inclusive'}
        matcher = TaxMatcher(tax_list_path=self._matcher.tax_list_path, train_dir=directory or TRAIN_DATA_DIR,
            alias_map_path=self._matcher.alias_map_path, confirmed_map_path=self._matcher.confirmed_map_path,
            industry=settings['industry'])
        save_settings(settings)
        self._settings, self._matcher = settings, matcher
        self._tax_catalog = None
        self._ai_cache.clear()
        self._ai_generation += 1
        return {'ok': True, 'state': self.get_state()}

    @synchronized
    def choose_history_directory(self) -> dict:
        if not self._window:
            return {'ok': False, 'message': '桌面窗口尚未就绪'}
        import webview
        result = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return {'ok': bool(result), 'path': result[0] if result else ''}

    @synchronized
    def open_history_directory(self) -> dict:
        directory = self._settings.get('history_dir', '') or TRAIN_DATA_DIR
        if not Path(directory).is_dir():
            return {'ok': False, 'message': '历史目录不存在'}
        if os.name == 'nt':
            os.startfile(directory)
            return {'ok': True}
        return {'ok': False, 'message': directory}

    def assist_tax(self, row_id: int) -> dict:
        with self._lock:
            if not self._ai_enabled or not self._ai_classifier.is_available():
                return {'ok': False, 'message': '请先启用并配置 AI 辅助'}
            original = self._item(row_id)
            if original.tax_confirmed:
                return {'ok': False, 'message': '已确认分类会保留；请对待确认商品使用 AI'}
            item = replace(original)
            key = (item.name, item.spec, item.unit, self._ai_classifier.model, self._matcher.industry, self._ai_generation)
            event = Event()
            previous = self._ai_jobs.get(row_id)
            if previous:
                previous.set()
            self._ai_jobs[row_id] = event
            matcher, classifier = self._matcher, self._ai_classifier
            cached = self._ai_cache.get(key)
            request = self._ai_inflight.get(key)
            owner = not cached and request is None
            if owner:
                request = {'done': Event(), 'item': None}
                self._ai_inflight[key] = request
        try:
            if cached:
                item = replace(cached)
            elif owner:
                try:
                    match_items_with_ai([item], matcher, classifier)
                    request['item'] = replace(item)
                finally:
                    request['done'].set()
            else:
                if not request['done'].wait(65) or request['item'] is None:
                    return {'ok': False, 'message': 'AI 请求未完成，请稍后重试'}
                item = replace(request['item'])
            with self._lock:
                current = next((value for value in self._items if value.row_id == row_id), None)
                if event.is_set() or matcher is not self._matcher or not current or current.tax_confirmed or (current.name, current.spec, current.unit) != key[:3]:
                    return {'ok': False, 'message': 'AI 结果已取消或商品已变化，未覆盖明细'}
                self._ai_cache[key] = replace(item)
                for field in fields(Item):
                    if field.name.startswith('tax_') and field.name != 'tax_rate':
                        setattr(current, field.name, getattr(item, field.name))
                current.tax_confirmed = False
                self._revision += 1
                self._save_draft()
                return {'ok': True, 'state': self.get_state()}
        finally:
            with self._lock:
                if self._ai_jobs.get(row_id) is event:
                    self._ai_jobs.pop(row_id, None)
                if owner and self._ai_inflight.get(key) is request:
                    self._ai_inflight.pop(key, None)

    @synchronized
    def cancel_ai(self, row_id: int) -> dict:
        event = self._ai_jobs.get(row_id)
        if event:
            event.set()
        return {'ok': True}

    def _item(self, row_id: int) -> Item:
        for item in self._items:
            if item.row_id == int(row_id):
                return item
        raise ValueError(f"找不到明细行：{row_id}")
