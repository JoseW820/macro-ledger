"""Data contracts shared by providers, pipeline and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


VALID_FREQUENCIES = {"monthly", "quarterly", "annual", "irregular"}
VALID_VALUE_TYPES = {
    "monthly_absolute",
    "monthly_yoy",
    "ytd_yoy",
    "ytd_absolute",
    "stock_level",
    "stock_yoy",
    "monthly_mom",
    "index_level",
    "month_end",
    "month_average",
    "quarterly_absolute",
}


@dataclass(frozen=True)
class IndicatorDefinition:
    indicator_id: str
    name: str
    theme: str
    frequency: str
    unit: str
    value_type: str
    primary_source: str
    fallback_sources: tuple[str, ...] = ()
    allow_cumulative: bool = False
    release_description: str = ""
    source_url_field: str = "source_url"
    homepage_core: bool = False
    definition: str = ""


@dataclass(frozen=True)
class DataPoint:
    indicator_id: str
    indicator_name: str
    period: str
    value: float | int | str | None
    unit: str
    frequency: str
    source: str
    source_url: str | None = None
    release_date: str | None = None
    retrieved_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    definition: str = ""
    calculation_method: str | None = None
    revision_status: str = "original"
    quality_status: str = "unverified"


@dataclass
class FetchResult:
    indicator: IndicatorDefinition
    period: str
    points: list[DataPoint] = field(default_factory=list)
    raw_artifact: str | None = None
    status: str = "not_implemented"
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityIssue:
    code: str
    message: str
    indicator_id: str | None = None
    period: str | None = None
    severity: str = "warning"


@dataclass
class RunSummary:
    period: str
    dry_run: bool
    planned_indicators: int
    completed: int = 0
    failed: int = 0
    issues: list[QualityIssue] = field(default_factory=list)
