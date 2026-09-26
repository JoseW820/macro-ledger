# 开源发布清单

## 发布前检查

- [ ] 删除或确认未提交 `data/`、`reports/`、`.env` 和本地日志。
- [ ] 用 `python -m macro_observer validate-config` 检查配置。
- [ ] 用 `python -m macro_observer doctor` 检查本机依赖和密钥状态。
- [ ] 用 `python -m macro_observer run --period YYYY-MM --dry-run` 验证新机器可运行。
- [ ] 用 `python -m pytest` 运行完整测试。
- [ ] 确认 README、数据源说明、指标定义和月度运行手册与当前网页一致。

## 用户首次使用

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev,spreadsheets]"
python -m macro_observer validate-config
python -m macro_observer web
```

打开 `http://127.0.0.1:8765/`，选择月份后从“导入月度数据包”开始。文件先进入预览，确认统计期和数值无误后才会写入数据库。

## 数据与隐私边界

- 用户原始文件只复制到项目本地 `data/incoming/`，删除上传记录不会删除电脑上的原始文件。
- 重复清理只保留每个“指标 + 统计期”的最新版本；历史版本仍可在上传记录中查看，直到用户主动移除。
- FRED API Key 只通过本机环境变量读取，不写入报告、SQLite、日志或前端存储。
- 项目不提供股票买卖建议，不用缺失值填充结论。

## CI 边界

GitHub Actions 只执行配置校验和不需要真实密钥的测试，不联网采集真实宏观数据。真实数据联调应在本机按月度运行手册执行。
