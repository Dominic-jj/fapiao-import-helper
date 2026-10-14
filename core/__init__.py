"""发票明细生成核心模块包。

所有内部引用统一使用包内相对导入（``from .models import Item``），
调用方统一使用 ``from core.xxx import yyy``，避免同一模块被重复加载两份。

调试单个模块时使用 ``python -m core.tax_matcher`` 而不是 ``python core/tax_matcher.py``。
"""
