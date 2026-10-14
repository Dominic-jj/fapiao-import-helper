"""核心数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, fields

from .config import round_money


@dataclass
class Item:
    """发票中的一个物品条目。

    业务字段用于模板输出；建议来源、置信度、复核提示和行标识用于页面交互。
    """

    name: str
    spec: str
    unit: str
    quantity: float
    unit_price: float
    amount: float
    tax_code: str = ""
    tax_name: str = ""
    # 税编建议来源：confirmed / alias / tax_list / summary_descendant / ai_rerank / 空
    tax_match_source: str = ""
    # AI 重排置信度，仅在来源为 ai_rerank 时有值
    tax_ai_confidence: str = ""
    tax_match_confidence: str = ""
    tax_review_reason: str = ""
    tax_standard_name: str = ""
    tax_confirmed: bool = False
    tax_rate: str = ""
    # 页面内稳定行标识，由 UI 层分配；0 表示尚未分配
    row_id: int = 0

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def compute_amount(quantity: float, unit_price: float) -> float:
    """金额始终由系统计算：``数量 * 单价``，并按金额精度取整。"""
    try:
        return round_money(float(quantity) * float(unit_price))
    except (TypeError, ValueError):
        return 0.0
