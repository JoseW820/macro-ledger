# 架构

数据流：Provider -> FetchResult -> 标准化数据 -> 质量检查/派生计算 -> SQLite/报告。

每次采集保存原始快照、来源地址、哈希、指标定义和统计期。SQLite 使用 `indicator_id + period + vintage` 保存修订版本，不覆盖历史观测。
