# 阶段三口径说明

## 外汇局三套口径

| Provider 指标 | 统计对象 | 是否可替代 |
| --- | --- | --- |
| `bank_settlement_balance_usd` | 银行与客户之间的结汇减售汇 | 不可替代银行代客涉外收付款 |
| `bank_cross_border_receipts_payments_balance_usd` | 银行代客实际涉外收入减支出 | 不等同于结售汇 |
| `international_balance_current_account` | 国际收支平衡表经常账户 | 按季度发布，不拆成月度 |

程序按 `series`、`table` 或 `series_type` 字段校验来源表，口径不匹配时返回
`definition_mismatch`，不会把三者合并为“资金流入”。

## 财政口径

一般公共预算收入、一般公共预算支出和政府债净融资分别入库。政府债净融资只表示
融资安排，不代表财政支出已经形成需求；报告层必须继续区分支出、项目开工和企业订单。

## 交叉核对表

`app.pipeline.crosscheck.cross_check_workbook` 只读用户提供的 XLSX，记录文件 SHA-256
和匹配结果，不覆盖官方原始响应或标准化数据。对齐表缺失、未安装 `openpyxl` 或数值
不一致都会形成明确状态。
