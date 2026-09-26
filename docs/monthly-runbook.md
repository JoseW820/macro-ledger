# 月度运行手册

1. 下载上月已经发布的官方文件，按月份整理到一个文件夹。
2. 执行 `python -m macro_observer doctor`，确认配置和 Excel 依赖。
3. 网页执行 `python -m macro_observer web`，选择月份后点击“导入月度数据包”。
4. 先点击“预览”，检查文件编号、统计期、数值和缺失项，再点击“确认导入”。
5. 在“已上传文件”中核对记录；如同一指标重复上传，点击“一键移除重复项”，只保留最新版本。
6. 点击“生成月报”或“导出 Agent 包”。
7. 命令行等价操作：`python -m macro_observer report --period YYYY-MM`、`python -m macro_observer agent-context --period YYYY-MM`。
8. 执行 `python -m macro_observer status --period YYYY-MM` 查看归档状态。

项目默认采用手动下载、手动上传模式。自动 Provider 和官网连通性检查属于可选扩展，不是月度运行的必要步骤。

## 本地网页工作台

保留效果图的页面结构作为本地操作界面：

```bash
python -m macro_observer web
```

浏览器打开 `http://127.0.0.1:8765/`。页面支持切换已有月份、查看标准化数据矩阵、上传官方 CSV/JSON/简单 Excel 表格、批量预览与确认、管理重复上传，以及生成 HTML 月报和 Agent 包。网页上传仍使用现有的文件校验、标准化和 SQLite 落库逻辑；复杂多层表格先整理成带有“统计期/数值”列的简单表格再导入。

失败数据源保留失败状态，不用上期值替代。

月报和 Agent 包只读取每个“指标 + 统计期”的最新标准化版本；“已上传文件”页面保留全部版本，供审计和清理。
