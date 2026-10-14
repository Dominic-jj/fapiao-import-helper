"""直接浏览税表原始分类，不受历史映射、规则或 AI 推荐限制。"""

from __future__ import annotations

from .product_terms import normalize_text
from .tax_reference import code_prefix, normalize_code


class TaxCatalog:
    def __init__(self, entries: list[dict]):
        self.entries = {entry['code']: entry for entry in entries}
        prefixes = {code_prefix(code): code for code in self.entries}
        self.parents: dict[str, str] = {}
        self.children: dict[str, list[str]] = {'': []}
        self.search_text = {}
        for code, entry in self.entries.items():
            prefix = code_prefix(code)
            parent = next((prefixes[prefix[:length]] for length in range(len(prefix) - 1, 0, -1)
                           if prefix[:length] in prefixes), '')
            self.parents[code] = parent
            self.children.setdefault(parent, []).append(code)
            self.search_text[code] = normalize_text(' '.join(str(entry.get(key, '')) for key in ('code', 'name', 'category', 'desc')))
        for codes in self.children.values():
            codes.sort()

    def payload(self, code: str) -> dict:
        entry = self.entries[code]
        name, category = entry['name'], entry.get('category', '')
        return {key: entry.get(key, '') for key in ('code', 'name', 'category', 'desc')} | {
            'display': f'{name}（{category}）' if category and category != name else name,
            'is_leaf': bool(entry.get('is_leaf', False)),
            'children_count': len(self.children.get(code, [])),
        }

    def path(self, code: str) -> list[dict]:
        result = []
        while code:
            result.append(self.payload(code))
            code = self.parents[code]
        return list(reversed(result))

    def browse(self, query: str = '', parent_code: str = '', offset: int = 0,
               page_size: int = 60, leaf_only: bool = False) -> dict:
        parent = normalize_code(parent_code)
        if parent and parent not in self.entries:
            raise ValueError('分类不在当前税表中')
        tokens = [normalize_text(token) for token in str(query or '').split() if token.strip()]
        prefix = code_prefix(parent) if parent else ''
        if tokens or leaf_only:
            codes = [code for code, entry in self.entries.items()
                     if (not parent or code_prefix(code).startswith(prefix))
                     and (not leaf_only or entry.get('is_leaf', False))
                     and all(token in self.search_text[code] for token in tokens)]
            normalized_query = normalize_text(query)
            codes.sort(key=lambda code: (code != normalized_query,
                normalize_text(self.entries[code]['name']) != normalized_query, code))
        else:
            codes = [parent] if parent and self.entries[parent].get('is_leaf', False) else self.children.get(parent, [])
        size = max(1, min(int(page_size), 100))
        # 返回真实页位置，末页删除/过滤后不会留下空白页。
        start = min(max(int(offset), 0), max(0, ((len(codes) - 1) // size) * size))
        return {
            'items': [self.payload(code) for code in codes[start:start + size]],
            'total': len(codes), 'offset': start, 'page_size': size,
            'path': self.path(parent) if parent else [],
            'roots': [self.payload(code) for code in self.children['']],
            'entry_count': len(self.entries),
        }

    def detail(self, code: str) -> dict:
        normalized = normalize_code(code)
        if normalized not in self.entries:
            raise ValueError('分类不在当前税表中')
        return {**self.payload(normalized), 'path': self.path(normalized)}
