"""桌面录入与导出共用的明细校验，无前端框架依赖。"""

from __future__ import annotations

import math

from .models import Item, compute_amount


def to_float(value) -> float | None:
    try:
        if value is None or not str(value).strip():
            return None
        number = float(str(value).strip().replace(",", "").replace("，", ""))
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def validate_item(item: Item) -> list[str]:
    errors = []
    if not item.name.strip():
        errors.append("物品名称不能为空")
    if not item.unit.strip():
        errors.append("单位不能为空")
    for field, value in (("数量", item.quantity), ("单价", item.unit_price)):
        number = to_float(value)
        if number is None:
            errors.append(f"{field}必须是有限数字")
        elif number < 0:
            errors.append(f"{field}不能小于零")
    if not errors and not math.isfinite(compute_amount(item.quantity, item.unit_price)):
        errors.append("计算金额超出有效范围")
    return [f"第 {item.row_id} 行：{error}" for error in errors]
