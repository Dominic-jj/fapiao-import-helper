"""五金/粤语品名解释。只提供真实商品线索，税编仍从本地税表读取。"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from .paths import HARDWARE_TERMS_PATH


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"\s+", "", text).translate(str.maketrans("電膠鋼銅鋁風頭絲線鎖閥燈齒", "电胶钢铜铝风头丝线锁阀灯齿"))


@dataclass(frozen=True)
class ProductProfile:
    standard_name: str
    tax_names: tuple[str, ...]
    requires_review: bool = False
    reason: str = ""
    material: str = ""
    history_resolves: bool = True


@lru_cache(maxsize=1)
def load_terms() -> list[dict]:
    with open(HARDWARE_TERMS_PATH, encoding="utf-8") as stream:
        data = json.load(stream)
    return data["rules"]


def describe_product(name: str, spec: str = "", unit: str = "") -> ProductProfile | None:
    normalized = normalize_text(name)
    # 商品名称含玩具/食品或明确整机时，不用局部五金词直接定类。
    if re.search(r'玩具|巧克力|糖果|滚筒洗衣机', normalized):
        return None
    context = normalize_text(f"{name} {spec}")
    for rule in load_terms():
        if not re.search(rule["pattern"], normalized, re.IGNORECASE):
            continue
        if rule.get("exclude") and re.search(rule["exclude"], normalized, re.IGNORECASE):
            continue
        details = rule
        for variant in rule.get("variants", []):
            if re.search(variant["pattern"], context, re.IGNORECASE):
                details = {**rule, **variant}
                break
        return ProductProfile(
            standard_name=details["standard_name"],
            tax_names=tuple(details["tax_names"]),
            requires_review=bool(details.get("requires_review", len(details["tax_names"]) != 1)),
            reason=details.get("reason", ""),
            material=details.get("material", ""),
            history_resolves=bool(details.get('history_resolves', True)),
        )
    return None
