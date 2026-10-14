# 内置资源与适用范围

- `resources/templates/invoice_template.xlsx`：项目现有电子税务局明细导入模板，保留工作表和列位置。来自项目初始资料，尚未记录官方下载日期或明确模板版本；使用前需与实际官方面板下载模板核对。
- `resources/reference/tax_list.xlsx`：项目现有商品和服务税收分类参考表。原始提供方、版本日期尚待作者补充，不宣称自动同步官方最新分类；所有候选须为表内具体叶子项。
- `resources/reference/hardware_terms.json`：公共五金品名解释规则，作为可选行业词库；提供候选而不是已确认商品。
- `resources/screenshots/`：用户提供并经隐私检查的操作说明图片；输入面板副本只保留开票信息区域。图片用于说明第三方工具的官方导入步骤。
- `resources/mappings/*.example.json` 和 `resources/samples/`：示例，不导入确认库。

MIT 许可证适用于本项目作者提供的代码与文档；第三方模板、税表和官方截图的权利归其各自权利人，不由本项目另行授予。模板来源、当前版本及公开分发范围需在正式 Release 前补充核实。
