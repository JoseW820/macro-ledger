# Macro Ledger

一个面向宏观数据爱好者的本地月度数据台账与分析工具。

这个项目的重点不是复杂的软件工程，而是把会计学习中的**记录、核验、分类、追溯和月度汇总**方法用于宏观数据整理：用户从官方网页或附件下载数据，导入后由项目统一保存、检查、生成 Agent 分析包，并把确认后的分析结果展示为月报。

## 项目定位

Macro Ledger 适合用于简历中展示以下能力：

- 将分散的官方宏观数据整理成可追溯的月度台账；
- 设计指标、统计期、单位、来源和质量状态的数据契约；
- 使用 SQLite 保存数据版本和导入记录；
- 对缺失、重复、口径不一致和异常值进行非阻断检查；
- 生成供外部 AI 使用的受约束 Agent 包；
- 将 AI 分析结果按宏观状态、主题和证据回流到月报页面。

它不是交易系统，也不提供股票买卖建议。

项目按月运行一次，处理上月已发布的官方数据，保存原始文件、统一指标口径，生成数据矩阵和中文宏观观察报告。数据采集既支持用户手动上传官方文件，也保留官方 Provider 和可选的 cnbs 核验适配层。

指标目录中的 `value_type` 明确区分：`monthly_absolute`（当月绝对量）、
`ytd_yoy`（累计同比）、`monthly_yoy`（当月同比）、`monthly_mom`（环比）、
`index_level`（指数值）、`stock_level`/`stock_yoy`（存量及存量同比）、
`month_end`、`month_average` 和 `quarterly_absolute`。每项指标同时记录是否允许累计值、
发布时间说明和来源链接字段，后续采集与审计都以此契约为准。

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

## 当前命令

```bash
python -m macro_observer --help
python -m macro_observer list-indicators
python -m macro_observer validate-config
python -m macro_observer report --period 2026-08
python -m macro_observer status --period 2026-08
python -m macro_observer doctor
python -m macro_observer web
python -m macro_observer agent-context --period 2026-08
```

`run`、`check-official-sources` 和各类 Provider 是保留的可选 CLI/适配器能力，不是网页默认工作流，也不要求用户配置 MCP、FRED 或其他 API。

网页和命令行导出的 Agent 分析包默认保存到项目自己的 `data/agent_context`。如需更换目录，可设置环境变量 `MACRO_AGENT_EXPORT_DIR`，或在命令行使用 `--output-dir`。

启动网页后访问 `http://127.0.0.1:8765/`。网页提供月份切换、数据矩阵、历史序列、官方 CSV/JSON/简单 Excel 导入、月度数据包预览与确认、已上传文件管理、月报生成，以及各官网数据发布时间说明。当前工作流是用户从官网手动下载后导入；复杂多层 Excel 建议先整理为包含“统计期”和“数值”列的简单表格。网页与命令行共用同一套标准化、质量检查、SQLite 和报告逻辑。

月报和 Agent 包只读取每个“指标 + 统计期”的最新标准化版本；“已上传文件”页面保留全部导入版本，便于审计和清理。“导出 Agent 包”会生成 `data/agent_context/YYYY-MM/` 及同名 ZIP，包含标准化事实、指标定义、质量报告和受约束的分析提示词。可以把 ZIP 交给外部 AI；AI 只能使用包内事实，缺失数据必须写“当前无法判断”，不得联网补数或提供交易建议。

Agent 分析结果支持按主题展开的推理结构。六个主题均可输出 `data_facts`、`what_data_indicates`、`cross_theme_links`、`logic_chain`、`future_implications`、`supporting_evidence`、`counter_evidence`、`unknowns`、`watchlist` 和 `data_refs`。其中跨主题关联只能引用 Agent 包内指标，逻辑链应区分数据事实、传导机制和条件式影响；旧版只含 `summary` 与证据字段的 JSON 仍可导入，但缺少的扩展段落会显示为“未提供”。

## 实际使用流程：手动下载、网页导入

项目当前最稳定、最适合普通用户的方式是：用户从国家统计局、人民银行、外汇局、财政部、海关或其他官方页面下载当月 Excel/CSV 文件，再在网页中导入。项目不假设这些官网提供稳定 API，也不会自动替用户寻找或下载全部数据。

1. 在官方网页下载上月已经发布的数据文件；
2. 按项目提供的月度数据清单整理文件名；
3. 启动网页并点击“导入月度数据包”；
4. 选择月份文件夹，先预览，再确认导入；
5. 在“已上传文件”中检查重复项和缺失项；
6. 导出 Agent 包交给外部 AI 分析；
7. 将 `analysis-result.json` 导回网页并确认；
8. 生成月报和数据矩阵。

也可以通过命令行导入单个国家统计局文件：

```bash
python -m macro_observer import-nbs-file \
  --indicator industrial_value_added_yoy \
  --period 2025-08 \
  --file data/incoming/nbs/industrial_value_added_yoy.csv
```

`data/incoming/`、`data/raw/`、`data/normalized/` 和 `reports/` 都是本机数据目录，已加入 `.gitignore`，不会提交到 GitHub。

## 可选适配器说明

代码中保留了国家统计局 HTTP、人民银行、外汇局、财政部、海关、中国货币网、FRED 和 cnbs 等 Provider，主要用于后续扩展、测试和有明确接口条件的用户。它们不是网页上传流程的前置条件，不能替代用户对官方文件的下载、口径确认和导入预览。

FRED API Key 只对选择使用 FRED CLI 适配器的用户有意义；当前网页不直接调用 FRED，也不会因为没有 API Key 而把数据填成 0。

项目提供非阻断质量检查、可追溯派生计算和主题状态模块。质量问题不会把缺失值填成 0，也不会把不同来源或代理口径混在一起。

如果选择使用可选的自动 Provider，国家统计局指标代码必须先经过目录核对，再通过命令行显式传入，例如：

```bash
python -m macro_observer run --period 2025-08 --only cpi_yoy --nbs-code cpi_yoy=已确认代码
```

自动 Provider 的结果写入 `data/raw/` 和 `data/normalized/`；网页上传同样会生成标准化记录并落库到 `data/macro_observer.sqlite`。接口失败、无数据和口径不匹配都会保留为明确状态，不会用相近指标替代。

## 项目边界

项目用于理解生产、需求、价格、信用、财政、房地产和外部平衡，不提供股票买卖建议。人民银行、海关、外汇局、财政和利率数据将在后续阶段按数据源分别接入。

## 简历中的项目描述

中文：独立设计并实现本地宏观数据月度台账工具，负责官方数据导入、指标口径核验、SQLite 版本追踪、数据质量检查、Agent 分析包和月报展示。

English: Built a local monthly macroeconomic data ledger that imports official files, validates indicator definitions, tracks data versions in SQLite, produces quality checks and structured AI analysis packages, and generates reviewable monthly reports.

## 本地路径与安全

默认数据目录是项目内的 `data/`，默认报告目录是 `reports/`。可以通过环境变量改变它们：

```env
MACRO_DATA_ROOT=data
MACRO_REPORT_DIR=reports
MACRO_AGENT_EXPORT_DIR=data/agent_context
```

这些目录只属于当前机器，不是项目代码的一部分。

## 开源和安全

复制 `.env.example` 为本机 `.env` 后再填写自己的 `FRED_API_KEY`。不要将 `.env`、数据库、原始下载文件或报告中的私有数据提交到仓库。当前 CLI 不实现网页密钥设置；FRED Key 设置入口属于后续本地网页 UI 工作，任何实现都必须由后端读取本地安全配置，不能放入浏览器 `localStorage`。

详见 [数据源](docs/data-sources.md)、[指标定义](docs/indicator-definitions.md)、[架构](docs/architecture.md)、[月度运行手册](docs/monthly-runbook.md) 和 [开源发布清单](docs/open-source-release-checklist.md)。
