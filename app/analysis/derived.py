"""Traceable derived calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from app.models import DataPoint


@dataclass(frozen=True)
class DerivedObservation:
    indicator_id: str
    period: str
    value: float | None
    formula: str
    inputs: tuple[str, ...]
    calculated_at: str


def trade_balance(exports: DataPoint, imports: DataPoint) -> DerivedObservation:
    if exports.period != imports.period:
        raise ValueError("出口和进口统计期不一致")
    return DerivedObservation("trade_balance_rmb_monthly", exports.period, float(exports.value) - float(imports.value), "exports - imports", (exports.indicator_id, imports.indicator_id), datetime.now(timezone.utc).isoformat())


def spread(left: DataPoint, right: DataPoint, *, indicator_id: str, formula: str = "left - right") -> DerivedObservation:
    if left.period != right.period:
        raise ValueError("利差输入统计期不一致")
    return DerivedObservation(indicator_id, left.period, float(left.value) - float(right.value), formula, (left.indicator_id, right.indicator_id), datetime.now(timezone.utc).isoformat())
