"""Non-blocking quality checks for normalized observations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

from app.models import DataPoint, IndicatorDefinition, QualityIssue


@dataclass(frozen=True)
class QualityReport:
    issues: tuple[QualityIssue, ...]


def check_points(
    points: Iterable[DataPoint],
    *,
    indicators: Mapping[str, IndicatorDefinition] | Iterable[IndicatorDefinition] | None = None,
    jump_threshold: float = 20.0,
) -> QualityReport:
    rows = list(points)
    issues: list[QualityIssue] = []
    if indicators is None:
        definitions: dict[str, IndicatorDefinition] = {}
    elif isinstance(indicators, Mapping):
        definitions = dict(indicators)
    else:
        definitions = {item.indicator_id: item for item in indicators}
    seen: set[tuple[str, str]] = set()
    by_indicator: dict[str, list[DataPoint]] = defaultdict(list)
    for point in rows:
        key = (point.indicator_id, point.period)
        if key in seen:
            issues.append(QualityIssue("duplicate_period", f"重复统计期: {point.indicator_id} {point.period}", point.indicator_id, point.period))
        seen.add(key)
        by_indicator[point.indicator_id].append(point)
        definition = definitions.get(point.indicator_id)
        if point.value is None:
            issues.append(QualityIssue("missing_value", "观测值为空", point.indicator_id, point.period))
        if point.frequency == "monthly" and len(point.period) != 7:
            issues.append(QualityIssue("frequency_mismatch", "月度数据统计期格式错误", point.indicator_id, point.period))
        if point.frequency == "quarterly" and not _is_quarter(point.period):
            issues.append(QualityIssue("frequency_mismatch", "季度数据统计期格式错误", point.indicator_id, point.period, "error"))
        if definition and point.unit != definition.unit:
            issues.append(QualityIssue("unit_mismatch", f"数据单位为 {point.unit}，配置单位为 {definition.unit}", point.indicator_id, point.period, "error"))
        if definition and isinstance(point.value, (int, float)) and not isinstance(point.value, bool):
            if definition.value_type in {"monthly_yoy", "ytd_yoy", "stock_yoy", "monthly_mom"} and abs(float(point.value)) > 100:
                issues.append(QualityIssue("scale_suspect", "百分比指标数值超过 ±100，疑似单位或口径错误", point.indicator_id, point.period, "error"))
            if definition.value_type == "index_level" and not 0 <= float(point.value) <= 100:
                issues.append(QualityIssue("range_suspect", "指数值不在 0-100 的常见范围内", point.indicator_id, point.period, "warning"))
    for indicator_id, observations in by_indicator.items():
        definition = definitions.get(indicator_id)
        if definition and definition.value_type in {"monthly_absolute", "ytd_absolute", "stock_level", "quarterly_absolute"}:
            continue
        ordered = sorted((p for p in observations if isinstance(p.value, (int, float))), key=lambda p: p.period)
        for previous, current in zip(ordered, ordered[1:]):
            if abs(float(current.value) - float(previous.value)) > jump_threshold:
                issues.append(QualityIssue("abnormal_jump", f"数值跳变超过阈值 {jump_threshold}", indicator_id, current.period, "warning"))
    _check_trade_balance(rows, issues)
    return QualityReport(tuple(issues))


def _is_quarter(period: str) -> bool:
    return len(period) == 7 and period[4:6] == "-Q" and period[-1:] in {"1", "2", "3", "4"}


def _check_trade_balance(rows: list[DataPoint], issues: list[QualityIssue]) -> None:
    grouped: dict[str, dict[str, DataPoint]] = defaultdict(dict)
    for point in rows:
        grouped[point.period][point.indicator_id] = point
    for period, values in grouped.items():
        exports = values.get("exports_rmb_monthly")
        imports = values.get("imports_rmb_monthly")
        balance = values.get("trade_balance_rmb_monthly")
        if not all(item and isinstance(item.value, (int, float)) for item in (exports, imports, balance)):
            continue
        expected = float(exports.value) - float(imports.value)
        if abs(expected - float(balance.value)) > 0.05:
            issues.append(QualityIssue("derived_mismatch", f"贸易差额应为出口减进口，计算值 {expected:g} 与记录值 {balance.value} 不一致", "trade_balance_rmb_monthly", period, "error"))
