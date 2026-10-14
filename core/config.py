"""全局业务配置。

只放“会被多个模块引用、且需要单点维护”的业务常量。
路径配置见 `core/paths.py`。
"""

from __future__ import annotations

# 默认税率（用户可核对并设置默认值或逐行修改，写入 H 列）。
TAX_RATE = "0.01"

# 金额、单价相关的小数位（模板要求金额最多 2 位小数）。
MONEY_DECIMALS = 2


def tax_rate_display(rate: str = TAX_RATE) -> str:
    """把税率原始值转成页面展示文案，例如 ``0.01`` -> ``1%``。"""
    try:
        percent = float(rate) * 100
    except (TypeError, ValueError):
        return rate
    return f"{percent:g}%"


def round_money(value: float) -> float:
    """金额统一取整，避免浮点误差写进 Excel。"""
    return round(float(value), MONEY_DECIMALS)
