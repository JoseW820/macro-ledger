"""Normalize official statistical payloads without changing their meaning."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.models import DataPoint, IndicatorDefinition


class NormalizationError(ValueError):
    """Raised when an official response cannot be mapped safely."""


class PeriodMismatchError(NormalizationError):
    """Raised when a response period does not match the requested period."""


_MONTH_RE = re.compile(r"(?P<year>\d{4})[-年/]?(?P<month>0?[1-9]|1[0-2])(?:月)?$")
_MONTH_COMBINED_RE = re.compile(r"(?:1[-—至]2|1、2|1和2)月")
_QUARTER_RE = re.compile(r"(?P<year>\d{4})[-年 ]?(?:Q|第)?(?P<quarter>[1-4])(?:季度|季)?$", re.I)
_QUARTER_CN_RE = re.compile(r"(?P<year>\d{4})年?第(?P<quarter>[一二三四1-4])季度$")
_YEAR_RE = re.compile(r"^(?P<year>\d{4})(?:年)?$")


def normalize_period(raw: Any, frequency: str) -> str:
    """Convert common NBS period labels to the project's canonical form.

    A combined January-February release is intentionally rejected because the
    project must never split it into two fabricated monthly observations.
    """

    text = str(raw).strip().replace("年", "-").replace("月", "")
    if _MONTH_COMBINED_RE.search(str(raw)) or re.search(r"^\d{4}[- ]?1[-—至]2", text):
        raise PeriodMismatchError(f"统计局合并发布期不可拆分: {raw}")
    if frequency == "monthly":
        match = _MONTH_RE.match(str(raw).strip())
        if not match:
            match = _MONTH_RE.match(text)
        if not match:
            raise NormalizationError(f"无法解析月度统计期: {raw}")
        return f"{int(match.group('year')):04d}-{int(match.group('month')):02d}"
    if frequency == "quarterly":
        match = _QUARTER_RE.match(str(raw).strip())
        if not match:
            match = _QUARTER_RE.match(text)
        if not match:
            match = _QUARTER_CN_RE.match(str(raw).strip())
            if match:
                quarter = {"一": "1", "二": "2", "三": "3", "四": "4"}.get(match.group("quarter"), match.group("quarter"))
                return f"{int(match.group('year')):04d}-Q{quarter}"
        if not match and re.fullmatch(r"\d{6}", str(raw).strip()) and str(raw).strip()[4:] in {"01", "02", "03", "04"}:
            return f"{str(raw).strip()[:4]}-Q{int(str(raw).strip()[4:])}"
        if not match:
            raise NormalizationError(f"无法解析季度统计期: {raw}")
        return f"{int(match.group('year')):04d}-Q{int(match.group('quarter'))}"
    if frequency == "annual":
        match = _YEAR_RE.match(str(raw).strip())
        if not match:
            match = _YEAR_RE.match(text)
        if not match:
            raise NormalizationError(f"无法解析年度统计期: {raw}")
        return match.group("year")
    if frequency == "irregular":
        return str(raw).strip()
    raise NormalizationError(f"不支持的频率: {frequency}")


def period_to_api_code(period: str, frequency: str) -> str:
    """Convert a canonical period into NBS column-code conventions."""

    if frequency == "monthly":
        if not re.fullmatch(r"\d{4}-\d{2}", period):
            raise NormalizationError(f"非法月度期: {period}")
        return period.replace("-", "")
    if frequency == "quarterly":
        match = re.fullmatch(r"(\d{4})-Q([1-4])", period)
        if not match:
            raise NormalizationError(f"非法季度期: {period}")
        return f"{match.group(1)}Q{match.group(2)}"
    if frequency == "annual":
        if not re.fullmatch(r"\d{4}", period):
            raise NormalizationError(f"非法年度期: {period}")
        return period
    return period


def parse_numeric(value: Any) -> float | int | str | None:
    """Parse a displayed number while preserving non-numeric missing markers."""

    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "…", "...", "null", "None"}:
        return None
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError:
        return str(value).strip()
    if percent:
        return number
    return int(number) if number.is_integer() else number


def _period_from_node(node: dict[str, Any], frequency: str) -> str | None:
    """Read a time dimension from a NBS data node."""

    for dimension in node.get("wds", []) or []:
        if not isinstance(dimension, dict):
            continue
        wdcode = str(dimension.get("wdcode", "")).lower()
        if wdcode in {"sj", "time", "date", "period"}:
            raw = dimension.get("valuecode", dimension.get("value"))
            if raw is not None:
                try:
                    return normalize_period(raw, frequency)
                except NormalizationError:
                    return None
    code = str(node.get("code", ""))
    match = re.search(r"(?:_|-)(\d{4}(?:\d{2}|Q[1-4]))$", code, re.I)
    if match:
        raw = match.group(1)
        if frequency == "monthly" and len(raw) == 6:
            raw = f"{raw[:4]}-{raw[4:]}"
        return normalize_period(raw, frequency)
    return None


def _is_national(node: dict[str, Any]) -> bool:
    """Reject nodes that explicitly identify a non-national region."""

    national_codes = {"00", "000000", "全国", "china", "national"}
    for dimension in node.get("wds", []) or []:
        if not isinstance(dimension, dict):
            continue
        wdcode = str(dimension.get("wdcode", "")).lower()
        if wdcode not in {"reg", "area", "region", "dq"}:
            continue
        code = str(dimension.get("valuecode", dimension.get("code", ""))).strip().lower()
        name = str(dimension.get("value", dimension.get("name", ""))).strip().lower()
        if code and code not in national_codes and name not in national_codes:
            return False
    return True


def _definition_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    returned = payload.get("returndata", payload)
    if isinstance(returned, dict):
        for key in ("name", "title", "unit", "frequency", "definition", "label"):
            if returned.get(key) is not None:
                parts.append(str(returned[key]))
        for node in returned.get("wdnodes", []) or []:
            if isinstance(node, dict):
                for key in ("name", "label", "value"):
                    if node.get(key) is not None:
                        parts.append(str(node[key]))
    return " ".join(parts)


def validate_definition_match(payload: dict[str, Any], indicator: IndicatorDefinition) -> None:
    """Fail closed on obvious frequency, geography or cumulative mismatches."""

    text = _definition_text(payload)
    if not text:
        return
    if indicator.frequency == "monthly" and any(word in text for word in ("季度", "quarter")):
        raise NormalizationError(f"口径不匹配：{indicator.indicator_id} 收到季度数据")
    if indicator.frequency == "quarterly" and "月度" in text:
        raise NormalizationError(f"口径不匹配：{indicator.indicator_id} 收到月度数据")
    if indicator.value_type in {"monthly_yoy", "monthly_mom"} and "累计" in text:
        raise NormalizationError(f"口径不匹配：{indicator.indicator_id} 不接受累计口径")
    if not indicator.allow_cumulative and "累计" in text:
        raise NormalizationError(f"口径不匹配：{indicator.indicator_id} 不允许累计值")


def normalize_nbs_payload(
    payload: dict[str, Any],
    indicator: IndicatorDefinition,
    requested_period: str | None,
    source_url: str,
    retrieved_at: str | None = None,
) -> list[DataPoint]:
    """Convert NBS ``datanodes`` to auditable DataPoint records."""

    validate_definition_match(payload, indicator)
    returned = payload.get("returndata", payload)
    if not isinstance(returned, dict):
        raise NormalizationError("统计局响应 returndata 不是对象")
    nodes = returned.get("datanodes", [])
    if not isinstance(nodes, list):
        raise NormalizationError("统计局响应 datanodes 不是列表")

    points: list[DataPoint] = []
    for node in nodes:
        if not isinstance(node, dict) or not _is_national(node):
            continue
        data = node.get("data", {})
        if isinstance(data, dict):
            value = data.get("data", data.get("value"))
            has_data = data.get("hasdata", True)
        else:
            value = data
            has_data = value not in (None, "", "-")
        if not has_data:
            continue
        period = _period_from_node(node, indicator.frequency)
        if period is None:
            continue
        if requested_period is not None and period != requested_period:
            continue
        parsed = parse_numeric(value)
        if parsed is None:
            continue
        points.append(
            DataPoint(
                indicator_id=indicator.indicator_id,
                indicator_name=indicator.name,
                period=period,
                value=parsed,
                unit=indicator.unit,
                frequency=indicator.frequency,
                source="nbs",
                source_url=source_url,
                release_date=None,
                retrieved_at=retrieved_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                definition=indicator.definition,
                calculation_method="official_value",
                revision_status="original",
                quality_status="unverified",
            )
        )
    if not points:
        raise LookupError(f"统计局无数据: {indicator.indicator_id} {requested_period}")
    return points


def save_normalized_points(points: Iterable[DataPoint], root: Path) -> Path:
    """Persist standardised observations as JSON without overwriting history."""

    point_list = list(points)
    if not point_list:
        raise ValueError("不能保存空的标准化数据")
    first = point_list[0]
    target_dir = root / first.indicator_id / first.period
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = first.retrieved_at.replace(":", "").replace("+00:00", "Z")
    target = target_dir / f"{stem}.json"
    suffix = 1
    while target.exists():
        target = target_dir / f"{stem}_{suffix}.json"
        suffix += 1
    target.write_text(
        json.dumps([asdict(point) for point in point_list], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def save_normalized_series(points: Iterable[DataPoint], root: Path) -> Path:
    """Persist a complete history as one immutable series artifact."""

    point_list = list(points)
    if not point_list:
        raise ValueError("不能保存空的标准化序列")
    first = point_list[0]
    target_dir = root / first.indicator_id / "series"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(":", "").replace("+00:00", "Z")
    target = target_dir / f"{stamp}.json"
    suffix = 1
    while target.exists():
        target = target_dir / f"{stamp}_{suffix}.json"
        suffix += 1
    target.write_text(
        json.dumps([asdict(point) for point in point_list], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target
