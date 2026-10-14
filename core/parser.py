"""手动输入文本解析。

本模块负责把用户连续粘贴或键入的明细文本解析为结构化 ``Item``。
当前主格式以键盘快速录入为优先：

```
物品名称 单位 数量 单价
规格 物品名称 单位 数量 单价
```

解析时从右往左识别单价、数量、单位，剩余内容再按首词是否像规格拆分。
金额始终由 ``数量 * 单价`` 计算。
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass

from .models import Item, compute_amount


@dataclass
class ParseError:
    """单行解析失败信息。"""

    line_number: int
    raw: str
    reason: str


# 仅作为常见单位参考，不再用于硬性校验。
KNOWN_UNITS = {
    "个", "只", "把", "条", "件", "台", "套", "组", "米", "箱",
    "盒", "包", "瓶", "罐", "块", "片", "张", "副", "对", "根",
    "支", "卷", "袋", "桶", "升", "吨", "公斤", "千克", "克", "批",
    "扎", "排", "项", "份", "次", "户", "人", "辆", "座", "盘",
    "架", "面", "孔", "芯", "平方", "平米", "平方米", "立方", "小时",
    "天", "月", "年", "m", "cm", "mm", "kg", "KG",
}

HEADER_KEYWORDS = ("物品名称", "数量", "单价")

# 千分位数字（1,000 / 1，234）不应被当成 CSV 分隔符。
_THOUSANDS_SEP_RE = re.compile(r"(?<=\d)[,，](?=\d{3}(?:\D|$))")


def _to_number(value: str) -> float | None:
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return None
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except ValueError:
        return None


def _is_header_line(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return all(keyword in compact for keyword in HEADER_KEYWORDS)


def looks_like_unit(token: str) -> bool:
    """判断单位字段是否非空。

    快速录入规则已经明确从右往左解析：单价、数量、单位。
    单位不再依赖白名单，避免“斤”等真实单位因未收录而解析失败。
    """

    text = str(token).strip()
    return bool(text)


def looks_like_spec(token: str) -> bool:
    """保守判断首词是否像规格型号。"""

    text = str(token).strip()
    if not text:
        return False
    if text in {"-", "无", "无规格"}:
        return True

    # 纯数字常见于“86 灯头”“20 管件”等规格。
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return True

    # 2x63A、30X60、4*25、16#、DN20 等。
    if re.search(r"\d", text) and re.search(r"[A-Za-z×xX*/\\.\-#＃]", text):
        return True

    # 1.2米、20厘米、10平方、6分、1寸、10厘、10方、2.5平、10丝、6号 等
    # （含英制管径单位 分/寸，及五金常见简写 厘/丝/方/平/号）。
    if re.fullmatch(
        r"\d+(?:\.\d+)?(?:毫米|厘米|平方米|平米|平方|米|mm|cm|m|分|寸|厘|丝|方|平|号|㎡|A|V|W|P|KW|kW|kw)",
        text,
    ):
        return True

    # 12芯、2位、5孔、6类、3极、4联、8门、3层 等（数字+中文量词/计量字）。
    if re.fullmatch(r"\d+(?:\.\d+)?[芯位孔极类联门层]", text):
        return True

    # BV2.5、PVC20、PPR25、M6 等行业常见型号。
    if re.fullmatch(r"(?:BV|BVR|RVV|PVC|PPR|DN|M)\d+[A-Za-z0-9.]*", text, re.IGNORECASE):
        return True

    # 单极、双极等电气规格。
    if text in {"单极", "双极", "三极", "四极"}:
        return True

    return False


def _build_item(name: str, spec: str, unit: str, quantity: float, unit_price: float) -> Item | None:
    name = str(name).strip()
    spec = "" if str(spec).strip() in {"-", "无", "无规格"} else str(spec).strip()
    unit = str(unit).strip()

    if not name:
        return None
    if not looks_like_unit(unit):
        return None

    return Item(
        name=name,
        spec=spec,
        unit=unit,
        quantity=quantity,
        unit_price=unit_price,
        amount=compute_amount(quantity, unit_price),
    )


def _split_delimited(line: str) -> list[str]:
    if "\t" in line:
        return [part.strip() for part in line.split("\t")]
    normalized = line.replace("，", ",")
    return [part.strip() for part in next(csv.reader([normalized]))]


def _parse_delimited_line(line: str) -> tuple[Item | None, str]:
    fields = _split_delimited(line)
    if len(fields) < 4:
        return None, "字段不足，至少需要 4 列"

    if len(fields) == 4:
        name, unit, qty_text, price_text = fields
        spec = ""
    else:
        # tab/CSV 粘贴优先按：物品名称、规格、单位、数量、单价。
        name, spec, unit, qty_text, price_text = fields[:5]

    quantity = _to_number(qty_text)
    unit_price = _to_number(price_text)
    if quantity is None or unit_price is None:
        return None, "数量或单价不是有效数字"
    if quantity < 0 or unit_price < 0:
        return None, "数量和单价不能小于零"
    if not math.isfinite(compute_amount(quantity, unit_price)):
        return None, "计算金额超出有效范围"

    item = _build_item(name, spec, unit, quantity, unit_price)
    if not item:
        return None, "物品名称或单位无效"
    return item, ""


def _parse_quick_line(line: str) -> tuple[Item | None, str]:
    parts = line.split()
    if len(parts) < 4:
        return None, "字段不足，请按“物品名称 单位 数量 单价”输入"

    unit_price = _to_number(parts[-1])
    quantity = _to_number(parts[-2])
    unit = parts[-3].strip()
    name_parts = parts[:-3]

    if unit_price is None or quantity is None:
        return None, "末尾两个字段应为数量和单价"
    if quantity < 0 or unit_price < 0:
        return None, "数量和单价不能小于零"
    if not math.isfinite(compute_amount(quantity, unit_price)):
        return None, "计算金额超出有效范围"
    if not looks_like_unit(unit):
        return None, "倒数第三个字段应为单位"
    if not name_parts:
        return None, "物品名称不能为空"

    spec = ""
    if len(name_parts) >= 2 and looks_like_spec(name_parts[0]):
        spec = "" if name_parts[0] in {"-", "无", "无规格"} else name_parts[0]
        name_parts = name_parts[1:]

    name = " ".join(name_parts).strip()
    item = _build_item(name, spec, unit, quantity, unit_price)
    if not item:
        return None, "物品名称或单位无效"
    return item, ""


def parse_text_line(line: str) -> Item | None:
    """解析单行文本，失败时返回 ``None``。"""

    item, _ = parse_text_line_detail(line)
    return item


def parse_text_line_detail(line: str) -> tuple[Item | None, str]:
    """解析单行文本，同时返回失败原因。"""

    raw = str(line).strip()
    if not raw:
        return None, "空行"
    if _is_header_line(raw):
        return None, "表头行"

    # 制表符/CSV 保留空列和分隔符；只在空格录入格式中去除千分位。
    if "\t" in raw:
        return _parse_delimited_line(raw)
    quick = _THOUSANDS_SEP_RE.sub("", raw)
    if len(quick.split()) >= 4 and "," not in quick and "，" not in quick:
        return _parse_quick_line(quick)
    if "," in raw or "，" in raw:
        return _parse_delimited_line(raw)
    return _parse_quick_line(raw)


def parse_text_lines(lines: list[str]) -> list[Item]:
    """批量解析文本行，无法解析的行会被跳过。"""

    items = []
    for line in lines:
        item = parse_text_line(line)
        if item:
            items.append(item)
    return items


def parse_text_block(text: str) -> tuple[list[Item], list[ParseError]]:
    """解析多行文本，返回成功条目和失败行。"""

    items: list[Item] = []
    errors: list[ParseError] = []

    for line_number, raw in enumerate(str(text).splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        item, reason = parse_text_line_detail(line)
        if item:
            items.append(item)
        elif reason != "表头行":
            errors.append(ParseError(line_number=line_number, raw=line, reason=reason))

    return items, errors


if __name__ == "__main__":
    examples = [
        "漏电开关 个 1 65",
        "2x63A 漏电开关 个 1 100",
        "公牛有线14座 组 4 38",
        "1.2米 LED灯管 支 8 15",
        "86 灯头 个 10 3",
        "物品名称\t规格\t单位\t数量\t单价",
        "LED灯管\t1.2米\t支\t8\t15",
    ]

    for example in examples:
        parsed = parse_text_line(example)
        print(example, "=>", parsed)
