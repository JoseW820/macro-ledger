"""Theme status summaries without collapsing them into one score."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from app.models import DataPoint


@dataclass(frozen=True)
class ThemeStatus:
    theme: str
    status: str
    supporting: tuple[str, ...]
    opposing: tuple[str, ...]
    unknown: tuple[str, ...]


def summarize_theme(theme: str, points: Mapping[str, DataPoint], *, expected: tuple[str, ...], positive_when_rising: tuple[str, ...] = ()) -> ThemeStatus:
    supporting: list[str] = []
    unknown: list[str] = []
    for indicator_id in expected:
        point = points.get(indicator_id)
        if point is None or not isinstance(point.value, (int, float)):
            unknown.append(indicator_id)
        elif indicator_id in positive_when_rising and float(point.value) > 0:
            supporting.append(indicator_id)
    if not supporting and unknown:
        status = "数据不足"
    elif supporting:
        status = "改善"
    else:
        status = "持平"
    return ThemeStatus(theme, status, tuple(supporting), (), tuple(unknown))
