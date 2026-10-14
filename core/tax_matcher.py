"""
税收分类匹配模块 - 根据 resources/reference/tax_list.xlsx 匹配物品的税收分类编码

加载 resources/reference/tax_list.xlsx，通过关键词模糊匹配，
为每个物品找到最合适的税收分类编码。
"""

import glob
import json
import logging
import os
import re
from datetime import date

import openpyxl

from .paths import BUNDLED_TRAIN_DATA_DIR, CONFIRMED_TAX_CODES_PATH, TAX_ALIASES_PATH, TAX_LIST_PATH, TRAIN_DATA_DIR
from .tax_reference import code_prefix, load_tax_entries, normalize_code as normalize_tax_code
from .product_terms import describe_product, normalize_text

logger = logging.getLogger(__name__)

# 历史样本 xlsx（页面导出的发票明细）列位置：A=项目名称，B=税收分类编码，数据从第 4 行开始。
TRAIN_SHEET_NAME_COLUMN = 0
TRAIN_SHEET_CODE_COLUMN = 1
TRAIN_DATA_START_ROW = 4

_DEFAULT_TAX_LIST = TAX_LIST_PATH
_DEFAULT_TRAIN_DIR = TRAIN_DATA_DIR
_DEFAULT_ALIAS_MAP = TAX_ALIASES_PATH
_DEFAULT_CONFIRMED_MAP = CONFIRMED_TAX_CODES_PATH


class TaxMatcher:
    """税收分类匹配器"""

    def __init__(self, tax_list_path: str = _DEFAULT_TAX_LIST,
                 train_dir: str = _DEFAULT_TRAIN_DIR,
                 alias_map_path: str = _DEFAULT_ALIAS_MAP,
                 confirmed_map_path: str | None = None,
                 industry: str = ''):
        self.entries: list[dict] = []
        self.code_to_entry: dict[str, dict] = {}
        self.confirmed_map: dict[str, str] = {}  # 独立人工确认映射 → 税收编码
        self.train_map: dict[str, str] = {}  # 物品名 → 税收编码
        self.alias_map: dict[str, str] = {}  # 本地别名/规则 → 税收编码
        self.industry = industry
        self.tax_list_path = tax_list_path
        self.alias_map_path = alias_map_path
        self.history_records: list[dict] = []
        self.confirmed_records: list[dict] = []
        self.history_stats = {'files': 0, 'records': 0, 'ignored': 0, 'conflicts': 0, 'errors': []}
        if confirmed_map_path is None:
            # 测试或临时 tax_list 不应意外读取项目真实确认数据。
            confirmed_map_path = (
                _DEFAULT_CONFIRMED_MAP
                if os.path.abspath(tax_list_path) == os.path.abspath(_DEFAULT_TAX_LIST)
                else ''
            )
        self.confirmed_map_path = confirmed_map_path or ''
        self._load(tax_list_path)
        self.name_to_entries = {}
        for entry in self.entries:
            if entry.get('is_leaf', False):
                self.name_to_entries.setdefault(entry['name'], []).append(entry)
        self._load_confirmed_map(self.confirmed_map_path)
        if os.path.abspath(train_dir) == os.path.abspath(_DEFAULT_TRAIN_DIR) and BUNDLED_TRAIN_DATA_DIR != TRAIN_DATA_DIR:
            self._load_train(BUNDLED_TRAIN_DATA_DIR)
        self._load_train(train_dir)
        self._load_alias_map(alias_map_path)

    @staticmethod
    def normalize_code(code) -> str:
        return normalize_tax_code(code)

    @staticmethod
    def _code_prefix(code: str) -> str:
        return code_prefix(code)

    def _load(self, path: str):
        """加载税收分类表"""
        self.entries = load_tax_entries(path)
        self.code_to_entry = {entry['code']: entry for entry in self.entries}

    def get_entry(self, code) -> dict | None:
        return self.code_to_entry.get(self.normalize_code(code))

    def is_leaf_code(self, code) -> bool:
        entry = self.get_entry(code)
        return bool(entry and entry.get('is_leaf', False))

    def validate_tax_code(self, code) -> tuple[bool, str]:
        normalized = self.normalize_code(code)
        if not normalized:
            return False, '税收分类编码不能为空'

        entry = self.get_entry(normalized)
        if not entry:
            return False, '税收分类编码不在 resources/reference/tax_list.xlsx 中'
        if not entry.get('is_leaf', False):
            return False, '该商品编码为汇总商品，请使用下级具体商编'
        return True, ''

    def get_leaf_descendants(self, code) -> list[dict]:
        entry = self.get_entry(code)
        if not entry:
            return []

        prefix = self._code_prefix(entry['code'])
        return [
            candidate
            for candidate in self.entries
            if candidate['code'] != entry['code']
            and candidate.get('is_leaf', False)
            and self._code_prefix(candidate['code']).startswith(prefix)
        ]

    def _load_train(self, train_dir: str):
        """加载训练数据（手动确认过的物品→编码映射），作为优先匹配。

        同时读取 _ground_truth.json 和目录内所有 xlsx 文件，
        统一按文件名时间戳升序处理，越新的文件覆盖旧的同名物品映射。
        直接向目录复制新 xlsx 文件即可自动生效（重启后）。
        """
        if not os.path.isdir(train_dir):
            return

        # 收集所有来源：(排序键, 来源类型, 路径/数据)
        # _ground_truth.json 中每个 key 就是文件名，用文件名作为排序键
        sources: list[tuple[str, str, object]] = []

        gt_path = os.path.join(train_dir, '_ground_truth.json')
        if os.path.exists(gt_path):
            try:
                with open(gt_path, 'r', encoding='utf-8') as f:
                    gt = json.load(f)
                if isinstance(gt, dict):
                    for fname, items in gt.items():
                        if isinstance(items, list):
                            sources.append((fname, 'json', items))
            except (OSError, ValueError) as exc:
                logger.warning("跳过无法读取的历史映射 %s：%s", gt_path, exc)

        for fpath in glob.glob(os.path.join(train_dir, '*.xlsx')):
            fname = os.path.basename(fpath)
            if fname.startswith('~$'):
                continue
            sources.append((fname, 'xlsx', fpath))

        # 按文件名排序（含时间戳，字典序 = 时间顺序），越新越后，后写覆盖前
        for _, src_type, data in sorted(sources, key=lambda x: x[0]):
            if src_type == 'json':
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get('name', '')).strip()
                    code = self.normalize_code(item.get('tax_code', ''))
                    if name and code:
                        self.train_map[name] = code
                        self.history_records.append({**item, 'name': name, 'tax_code': code, 'source_file': '历史 JSON'})
            else:
                try:
                    wb = openpyxl.load_workbook(data, read_only=True, data_only=True)
                    try:
                        if '1-明细模板' not in wb.sheetnames:
                            raise ValueError('缺少 1-明细模板 工作表')
                        ws = wb['1-明细模板']
                        # 部分官方模板的维度缓存不准确，必须读取实际行。
                        ws.reset_dimensions()
                        header = next(ws.iter_rows(min_row=3, max_row=3, values_only=True), ())
                        if len(header) < 2 or '项目名称' not in str(header[0]) or '编码' not in str(header[1]):
                            raise ValueError('表头不符合标准明细模板')
                        self.history_stats['files'] += 1
                        for row in ws.iter_rows(min_row=TRAIN_DATA_START_ROW, values_only=True):
                            if len(row) <= max(TRAIN_SHEET_NAME_COLUMN, TRAIN_SHEET_CODE_COLUMN):
                                continue
                            name, code = row[TRAIN_SHEET_NAME_COLUMN], row[TRAIN_SHEET_CODE_COLUMN]
                            if name and code:
                                self.train_map[str(name).strip()] = self.normalize_code(code)
                                self.history_records.append({'name': str(name).strip(), 'tax_code': self.normalize_code(code),
                                    'spec': str(row[2] or '') if len(row) > 2 else '',
                                    'unit': str(row[3] or '') if len(row) > 3 else '', 'source_file': os.path.basename(data)})
                    finally:
                        wb.close()
                except Exception as exc:
                    # 单个样本损坏不应影响其余映射，但要留下排查线索。
                    logger.warning("跳过无法读取的历史样本 %s：%s", data, exc)
                    self.history_stats['ignored'] += 1
                    self.history_stats['errors'].append(f'{os.path.basename(data)}：{exc}')
        self.history_stats['records'] = len(self.history_records)
        groups = {}
        for record in self.history_records:
            groups.setdefault((normalize_text(record['name']), self.context_key(record.get('spec', ''), record.get('unit', ''))), set()).add(record['tax_code'])
        self.history_stats['conflicts'] = sum(len(codes) > 1 for codes in groups.values())

    def _load_confirmed_map(self, confirmed_map_path: str):
        """加载独立人工确认映射，作为最高优先级匹配来源。"""
        if not confirmed_map_path or not os.path.exists(confirmed_map_path):
            return

        try:
            with open(confirmed_map_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(data, dict):
            return

        for item_name, value in data.items():
            name = str(item_name).strip()
            if not name:
                continue
            if isinstance(value, dict):
                code = value.get('tax_code') or value.get('code')
            else:
                code = value
            normalized_code = self.normalize_code(code)
            if normalized_code:
                self.confirmed_map[name] = normalized_code
            if isinstance(value, dict):
                contexts = value.get('contexts', [])
                if not isinstance(contexts, list):
                    logger.warning('跳过格式无效的确认上下文，原文件保留')
                    continue
                for record in contexts:
                    if isinstance(record, dict) and record.get('tax_code'):
                        self.confirmed_records.append({**record, 'name': name})

    def _read_confirmed_file(self) -> dict:
        if not self.confirmed_map_path or not os.path.exists(self.confirmed_map_path):
            return {}

        try:
            with open(self.confirmed_map_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError) as exc:
            raise ValueError(f'确认映射无法读取，原文件已保留：{exc}') from exc

        if not isinstance(data, dict):
            raise ValueError('确认映射不是 JSON 对象，原文件已保留')
        return data

    def save_confirmed_tax_code(
        self,
        item_name: str,
        tax_code: str,
        tax_name: str = '',
        spec: str = '',
        unit: str = '',
    ) -> tuple[bool, str]:
        """保存用户确认后的物品名 → 税编映射。"""
        name = str(item_name).strip()
        if not name:
            return False, '物品名称不能为空'

        normalized_code = self.normalize_code(tax_code)
        is_valid, message = self.validate_tax_code(normalized_code)
        if not is_valid:
            return False, message

        if not self.confirmed_map_path:
            self.confirmed_map_path = _DEFAULT_CONFIRMED_MAP

        entry = self.get_entry(normalized_code)
        confirmed_name = str(tax_name or (entry or {}).get('name', '')).strip()
        try:
            data = self._read_confirmed_file()
        except ValueError as exc:
            return False, str(exc)
        old = data.get(name, {})
        contexts = old.get('contexts', []) if isinstance(old, dict) else []
        if not isinstance(contexts, list) or any(not isinstance(record, dict) for record in contexts):
            return False, '确认映射上下文格式无效，原文件已保留'
        contexts = list(contexts)
        key = self.context_key(spec, unit)
        contexts = [record for record in contexts if self.context_key(record.get('spec', ''), record.get('unit', '')) != key]
        contexts.append({'spec': spec, 'unit': unit, 'tax_code': normalized_code, 'tax_name': confirmed_name})
        data[name] = {
            'tax_code': normalized_code,
            'tax_name': confirmed_name,
            'source': 'manual_confirmed',
            'updated_at': date.today().isoformat(),
            'contexts': contexts,
        }

        temp_path = f'{self.confirmed_map_path}.tmp'
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.confirmed_map_path)), exist_ok=True)
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write('\n')
            os.replace(temp_path, self.confirmed_map_path)
        except OSError as exc:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            return False, f'写入确认映射失败：{exc}'

        self.confirmed_map[name] = normalized_code
        self.confirmed_records = [record for record in self.confirmed_records if record['name'] != name]
        self.confirmed_records.extend({**record, 'name': name} for record in contexts)
        return True, ''

    @staticmethod
    def context_key(spec: str, unit: str) -> tuple[str, str]:
        # 去掉明确的尺寸形式，保留材质/用途/型号线索；单位作为必要上下文。
        text = normalize_text(spec)
        text = re.sub(r'm\d+(?:[x×]\d+(?:\.\d+)?)?|\d+(?:\.\d+)?(?:mm|cm|毫米|厘米)|\d+(?:\.\d+)?[x×]\d+(?:\.\d+)?', '', text)
        return text, normalize_text(unit)

    def _context_candidates(self, item_name: str, spec: str, unit: str, top_n: int) -> list[dict]:
        key = self.context_key(spec, unit)
        for records, source in ((self.confirmed_records, 'confirmed_context'), (self.history_records, 'history')):
            same_name = [record for record in records if normalize_text(record['name']) == normalize_text(item_name)]
            compatible = [record for record in same_name if self.context_key(record.get('spec', ''), record.get('unit', '')) == key]
            selected = compatible or same_name
            if not selected:
                continue
            codes = list(dict.fromkeys(self.normalize_code(record.get('tax_code')) for record in selected))
            results = []
            for code in codes:
                results.extend(self._candidates_from_code(item_name, code, top_n, source, source + '_parent'))
            for candidate in results:
                parent_review = bool(candidate.get('requires_review'))
                reusable = source == 'confirmed_context' and bool(compatible) and len(codes) == 1 and not parent_review
                reason = candidate.get('review_reason', '')
                candidate.update(reusable=reusable, confidence='high' if reusable else 'low',
                    requires_review=parent_review or len(codes) > 1 or (source == 'confirmed_context' and not compatible))
                candidate['review_reason'] = '' if reusable else (reason or ('历史有同名不同编码或属性不足，请核对' if len(codes) > 1 or not compatible else '历史商品建议，请核对后确认'))
                if not candidate.get('is_leaf'):
                    candidate['requires_review'] = True
            if results:
                return results[:top_n]
        return []

    def _load_alias_map(self, alias_map_path: str):
        """加载本地明确别名映射，作为历史确认之后的第二优先级。

        支持三种格式：
        1. 扁平：{ "钢扎带": "1080417000000000000" }
        2. 带 tax_code：{ "玻璃胶": {"tax_code": "1070215030000000000"} }
        3. 分组嵌套 + `_` 前缀注释键：
           {
             "_说明": "分组说明",
             "_手动工具": {
               "螺丝刀": "1080404060000000000",
               "钳子": {"tax_code": "1080404030000000000"}
             }
           }

        递归展开任意深度的分组对象；`_` 开头的键视为注释/分组说明，
        其标量值直接跳过，其 dict 值则继续递归（因此分组头不污染映射）。
        """
        if not alias_map_path or not os.path.exists(alias_map_path):
            return

        try:
            with open(alias_map_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(data, dict):
            return

        def walk(node: dict) -> None:
            for raw_name, value in node.items():
                name = str(raw_name).strip()
                if not name:
                    continue
                if name.startswith('_'):
                    # 注释/分组说明：标量跳过，dict 继续递归（不当作品项）。
                    if isinstance(value, dict):
                        walk(value)
                    continue
                if isinstance(value, dict):
                    code = value.get('tax_code') or value.get('code')
                else:
                    code = value
                normalized_code = self.normalize_code(code)
                if normalized_code:
                    self.alias_map[name] = normalized_code

        walk(data)

    def _extract_keywords(self, text: str) -> list[str]:
        """
        从物品名中提取关键词（中文子串）。

        "空气开关" → ["空气开关", "空气", "开关"]
        "平板灯" → ["平板灯", "平板", "板灯", "灯"]
        """
        # 提取连续中文
        chinese_parts = re.findall(r'[\u4e00-\u9fff]+', text)
        keywords = []
        for part in chinese_parts:
            keywords.append(part)
            # 2-gram 分词
            if len(part) >= 2:
                for i in range(len(part) - 1):
                    keywords.append(part[i:i+2])
            # 尾部单字（产品类型）
            # 单字尾缀容易把电笔匹配到铅笔、扎带匹配到安全带。

        # 去重并按长度降序（优先匹配长词）
        seen = set()
        unique = []
        for kw in sorted(keywords, key=len, reverse=True):
            if kw not in seen:
                seen.add(kw)
                unique.append(kw)
        # 常见标准品名的通用同义召回，不依赖五金行业简称词库。
        if text.strip() in {'螺丝', '螺钉', '螺栓', '螺母', '垫圈'}:
            unique.append('紧固件')
        return unique

    def _score_entry(
        self,
        item_name: str,
        entry: dict,
        keywords: list[str],
        suffix_keywords: set[str],
    ) -> float:
        ename = entry['name']
        desc = entry['desc']
        score = 0.0
        has_name_match = False
        has_desc_match = False
        matched_keywords = 0

        # 完整物品名匹配（最高优先级）
        if item_name == ename or (len(ename) >= 2 and ename in item_name) or (len(item_name) >= 2 and item_name in ename):
            score += min(len(item_name), len(ename)) * 10
            has_name_match = True
            matched_keywords = len(keywords)

        if len(item_name) >= 2 and item_name in desc:
            score += len(item_name) * 8
            has_desc_match = True
            matched_keywords = max(matched_keywords, 1)

        # 逐个关键词匹配
        for kw in keywords:
            if len(kw) < 2:
                continue
            weight = len(kw) * 3
            if kw in suffix_keywords:
                if kw == item_name[-1:]:
                    weight += 10
                elif kw == item_name[-2:]:
                    weight += 6
                elif kw == item_name[-3:]:
                    weight += 4
            if kw in ename:
                score += weight
                has_name_match = True
                matched_keywords += 1
            elif kw in desc:
                score += weight * 0.6
                has_desc_match = True
                matched_keywords += 1

        if not has_name_match and not has_desc_match:
            return 0.0
        if not has_name_match:
            score *= 0.6

        if matched_keywords >= 2:
            score *= 1.5

        return score

    def _apply_rank_bonus(self, score: float, entry: dict) -> float:
        if score <= 0:
            return 0.0

        code = entry['code']
        if entry.get('is_leaf', True):
            score += 8
        else:
            score -= 10
        if code.startswith('109'):
            score += 3
        elif code.startswith('108'):
            score += 2
        elif code.startswith('1'):
            score += 2
        score -= len(entry['name']) * 0.05
        return score

    def _rank_entries(
        self,
        item_name: str,
        entries: list[dict],
        top_n: int,
        score_offset: float = 0.0,
    ) -> list[dict]:
        keywords = self._extract_keywords(item_name)
        suffix_keywords = self._suffix_keywords(item_name)
        scored = []

        for entry in entries:
            score = self._score_entry(item_name, entry, keywords, suffix_keywords)
            if score <= 0:
                score = 1.0
            score = self._apply_rank_bonus(score, entry) + score_offset
            if score > 0:
                scored.append({**entry, 'score': score})

        scored.sort(key=lambda e: e['score'], reverse=True)
        return scored[:top_n]

    def _suffix_keywords(self, item_name: str) -> set[str]:
        suffix_keywords = set()
        for n in [1, 2, 3]:
            if len(item_name) >= n:
                suffix_keywords.add(item_name[-n:])
        return suffix_keywords

    def _candidates_from_code(
        self,
        item_name: str,
        code: str,
        top_n: int,
        source: str,
        parent_source: str,
    ) -> list[dict]:
        normalized_code = self.normalize_code(code)
        if not normalized_code:
            return []

        entry = self.get_entry(normalized_code)
        if not entry:
            return []

        if entry.get('is_leaf', False):
            return [{**entry, 'score': 9999, 'source': source}]

        descendants = self.get_leaf_descendants(normalized_code)
        candidates = self._rank_entries(
            item_name,
            descendants,
            top_n=top_n,
            score_offset=9000,
        )
        for candidate in candidates:
            candidate['source'] = parent_source
            candidate['requires_review'] = True
            candidate['confidence'] = 'low'
            candidate['review_reason'] = '历史映射仅有汇总编码，请确认下级具体商品'
            candidate['parent_code'] = entry['code']
            candidate['parent_name'] = entry['name']
        return candidates

    def _confirmed_candidates(self, item_name: str, top_n: int) -> list[dict]:
        for code in (self.confirmed_map.get(item_name), self.train_map.get(item_name)):
            candidates = self._candidates_from_code(
                item_name, code, top_n, source='confirmed', parent_source='confirmed_parent',
            )
            if candidates:
                return candidates
        return []

    def _alias_candidates(self, item_name: str, top_n: int) -> list[dict]:
        alias_code = self.alias_map.get(item_name)
        return self._candidates_from_code(
            item_name,
            alias_code,
            top_n,
            source='alias',
            parent_source='alias_parent',
        )

    def match_candidates(
        self,
        item_name: str,
        top_n: int = 20,
        include_summary: bool = False,
        spec: str = '',
        unit: str = '',
    ) -> list[dict]:
        """
        为物品匹配税收分类编码，返回 Top-N 候选列表。

        每个候选包含 code, name, category, desc, score, is_leaf 字段，
        按 score 降序排列。

        Args:
            item_name: 物品名称
            top_n: 返回的最大候选数量

        Returns:
            候选列表 [{code, name, category, desc, score, is_leaf}, ...]
        """
        item_name = item_name.strip()
        if not item_name or top_n <= 0:
            return []
        contextual = self._context_candidates(item_name, spec, unit, top_n)
        profile = describe_product(item_name, spec, unit) if self.industry == 'hardware' else None
        domain_candidates = []
        if profile:
            for tax_name in profile.tax_names:
                for entry in self.name_to_entries.get(tax_name, []):
                    domain_candidates.append({
                        **entry, 'score': 8000 - len(domain_candidates), 'source': 'hardware_rule',
                        'standard_name': profile.standard_name, 'material': profile.material,
                        'confidence': 'low' if profile.requires_review else 'high',
                        'requires_review': profile.requires_review,
                        'review_reason': profile.reason,
                    })
        allowed_codes = {candidate['code'] for candidate in domain_candidates}

        if contextual:
            if contextual[0]['source'].startswith('history') and allowed_codes and contextual[0]['code'] not in allowed_codes:
                reason = '历史分类与当前商品线索不符，请按实际商品复核'
                for candidate in contextual:
                    candidate.update(requires_review=True, reusable=False, review_reason=reason)
                contextual += [{**candidate, 'requires_review': True, 'review_reason': reason} for candidate in domain_candidates]
            return contextual[:top_n]

        def check_history(candidates, trusted=True):
            if not candidates or not domain_candidates:
                return candidates
            compatible = candidates[0]['code'] in allowed_codes
            if compatible and not candidates[0].get('requires_review') and ((trusted and profile.history_resolves) or not profile.requires_review):
                return [{**candidate, 'confidence': 'high',
                         'standard_name': profile.standard_name} for candidate in candidates]
            # 旧样本/别名中的替代开票码不能成为正确商品的自动匹配依据。
            reason = (candidates[0].get('review_reason') or profile.reason or '请确认真实商品材质与用途') if compatible else f"历史/别名分类“{candidates[0]['name']}”与“{profile.standard_name}”不符，请按真实商品重新确认"
            return [{**candidate, 'requires_review': True, 'confidence': 'low',
                     'review_reason': reason, 'standard_name': profile.standard_name}
                    for candidate in candidates] + [
                        {**candidate, 'requires_review': True, 'confidence': 'low', 'review_reason': reason}
                        for candidate in domain_candidates if candidate['code'] not in {c['code'] for c in candidates}
                    ]

        # 训练数据精确匹配 → 最高优先级，但若历史记录是汇总编码，
        # 必须继续下钻到标准税编表中的具体下级编码。
        confirmed = self._confirmed_candidates(item_name, top_n)
        if confirmed:
            return check_history(confirmed)[:top_n]

        alias = self._alias_candidates(item_name, top_n)
        if alias:
            return check_history(alias, trusted=False)[:top_n]

        if domain_candidates:
            return domain_candidates[:top_n]

        keywords = self._extract_keywords(item_name)

        if not keywords:
            return []

        # 物品名的尾部通常是产品类型（如"空气开关"的"开关"、"平板灯"的"灯"）
        suffix_keywords = self._suffix_keywords(item_name)
        scored_by_code: dict[str, dict] = {}
        summary_hits: list[tuple[float, dict]] = []

        for entry in self.entries:
            base_score = self._score_entry(item_name, entry, keywords, suffix_keywords)
            if base_score <= 0:
                continue

            score = self._apply_rank_bonus(base_score, entry)
            if entry.get('is_leaf', False) or include_summary:
                scored_by_code[entry['code']] = {**entry, 'score': score, 'source': 'tax_list'}

            if not entry.get('is_leaf', False):
                summary_hits.append((score, entry))

        # 如果命中的是汇总编码，把命中信号传给它下面的具体编码。
        # 这样既不输出汇总编码，也不会因为具体子项名称没直接命中而丢候选。
        for summary_score, summary in summary_hits:
            for leaf in self.get_leaf_descendants(summary['code']):
                child_base = self._score_entry(item_name, leaf, keywords, suffix_keywords)
                if child_base > 0:
                    child_score = self._apply_rank_bonus(child_base, leaf)
                    score = max(child_score, summary_score * 0.75 + child_score * 0.25)
                else:
                    score = summary_score * 0.65 + self._apply_rank_bonus(1.0, leaf) * 0.1

                existing = scored_by_code.get(leaf['code'])
                if score > 0 and (not existing or score > existing['score']):
                    scored_by_code[leaf['code']] = {
                        **leaf,
                        'score': score,
                        'source': 'summary_descendant',
                        'parent_code': summary['code'],
                        'parent_name': summary['name'],
                    }

        # 通用模式只使用规格明确给出的材质线索改善排序，不据此自动确认。
        spec_text = normalize_text(spec)
        materials = {'铜': ('铜',), '铝': ('铝',), '不锈钢': ('钢', '铁'),
                     '塑料': ('塑料',), '橡胶': ('橡胶',), '纸制': ('纸',)}
        explicit = [targets for material, targets in materials.items() if material in spec_text]
        for candidate in scored_by_code.values():
            if explicit and any(any(term in candidate['name'] for term in targets) for targets in explicit):
                candidate['score'] += 100
        scored = sorted(scored_by_code.values(), key=lambda e: e['score'], reverse=True)
        for candidate in scored:
            # 未认识的商品只提供候选；单字、品牌和设备说明不能自动决定商品编码。
            exact_name = normalize_text(item_name) == normalize_text(candidate['name'])
            candidate['confidence'] = 'high' if exact_name else 'low'
            candidate['requires_review'] = not exact_name
            candidate['review_reason'] = '' if exact_name else '仅有字面相似候选，请确认商品用途、材质或补充规格'
        return scored[:top_n]

    def match(self, item_name: str) -> tuple[str, str]:
        """为物品匹配税收分类编码（返回 Top-1 结果）。"""
        candidates = self.match_candidates(item_name, top_n=1)
        if candidates and not candidates[0].get('requires_review'):
            return candidates[0]['code'], candidates[0]['name']
        return '', ''

    def match_items(self, items: list) -> list:
        """
        为多个物品匹配税收分类。

        Args:
            items: parser.Item 列表

        Returns:
            填充了 tax_code 和 tax_name 的 items
        """
        for item in items:
            code, name = self.match(item.name)
            item.tax_code = code
            item.tax_name = name
        return items


if __name__ == '__main__':
    matcher = TaxMatcher()

    test_names = [
        '插座',
        '插座',
        '空气开关',
        '平板灯',
        '热水器',
        '时控开关',
        '电线',
    ]

    for name in test_names:
        code, category = matcher.match(name)
        print(f'{name:10s} → {code}  {category}')
