"""Load and validate project configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import IndicatorDefinition, VALID_FREQUENCIES, VALID_VALUE_TYPES


class ConfigError(ValueError):
    """Raised when project configuration is invalid."""


REQUIRED_INDICATOR_FIELDS = {
    "indicator_id",
    "name",
    "theme",
    "frequency",
    "unit",
    "value_type",
    "primary_source",
    "fallback_sources",
    "allow_cumulative",
    "release_description",
    "source_url_field",
    "homepage_core",
    "definition",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"配置根节点必须是对象: {path}")
    return data


def load_indicators(config_dir: Path) -> list[IndicatorDefinition]:
    raw = _read_yaml(config_dir / "indicators.yaml")
    entries = raw.get("indicators")
    if not isinstance(entries, list):
        raise ConfigError("indicators.yaml 的 indicators 必须是列表")

    definitions: list[IndicatorDefinition] = []
    seen: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"第 {index} 个指标必须是对象")
        missing = REQUIRED_INDICATOR_FIELDS - set(entry)
        if missing:
            raise ConfigError(f"指标 {index} 缺少字段: {', '.join(sorted(missing))}")
        indicator_id = str(entry["indicator_id"])
        if indicator_id in seen:
            raise ConfigError(f"重复的 indicator_id: {indicator_id}")
        seen.add(indicator_id)
        frequency = str(entry["frequency"])
        value_type = str(entry["value_type"])
        if frequency not in VALID_FREQUENCIES:
            raise ConfigError(f"{indicator_id} 的 frequency 无效: {frequency}")
        if value_type not in VALID_VALUE_TYPES:
            raise ConfigError(f"{indicator_id} 的 value_type 无效: {value_type}")
        fallback_sources = entry["fallback_sources"]
        if not isinstance(fallback_sources, list) or not all(isinstance(item, str) for item in fallback_sources):
            raise ConfigError(f"{indicator_id} 的 fallback_sources 必须是字符串列表")
        if not isinstance(entry["allow_cumulative"], bool):
            raise ConfigError(f"{indicator_id} 的 allow_cumulative 必须是布尔值")
        for field_name in ("release_description", "source_url_field"):
            if not isinstance(entry[field_name], str) or not entry[field_name].strip():
                raise ConfigError(f"{indicator_id} 的 {field_name} 必须是非空字符串")
        definitions.append(
            IndicatorDefinition(
                indicator_id=indicator_id,
                name=str(entry["name"]),
                theme=str(entry["theme"]),
                frequency=frequency,
                unit=str(entry["unit"]),
                value_type=value_type,
                primary_source=str(entry["primary_source"]),
                fallback_sources=tuple(fallback_sources),
                allow_cumulative=entry["allow_cumulative"],
                release_description=str(entry["release_description"]),
                source_url_field=str(entry["source_url_field"]),
                homepage_core=bool(entry["homepage_core"]),
                definition=str(entry["definition"]),
            )
        )
    if not definitions:
        raise ConfigError("指标目录不能为空")
    return definitions


def load_sources(config_dir: Path) -> dict[str, Any]:
    raw = _read_yaml(config_dir / "sources.yaml")
    sources = raw.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise ConfigError("sources.yaml 的 sources 不能为空")
    return sources


def load_release_calendar(config_dir: Path) -> dict[str, Any]:
    return _read_yaml(config_dir / "release_calendar.yaml")


def load_confirmed_nbs_codes(config_dir: Path) -> dict[str, Any]:
    path = config_dir / "nbs_confirmed_codes.yaml"
    if not path.exists():
        return {}
    raw = _read_yaml(path)
    confirmed = raw.get("confirmed_series", {})
    if not isinstance(confirmed, dict):
        raise ConfigError("nbs_confirmed_codes.yaml 的 confirmed_series 必须是对象")
    return confirmed


def validate_config(config_dir: Path) -> tuple[list[IndicatorDefinition], dict[str, Any], dict[str, Any]]:
    indicators = load_indicators(config_dir)
    sources = load_sources(config_dir)
    calendar = load_release_calendar(config_dir)
    load_confirmed_nbs_codes(config_dir)
    source_names = set(sources)
    for indicator in indicators:
        referenced = {indicator.primary_source, *indicator.fallback_sources}
        missing_sources = referenced - source_names
        if missing_sources:
            raise ConfigError(
                f"指标 {indicator.indicator_id} 引用了未配置来源: {', '.join(sorted(missing_sources))}"
            )
    if not isinstance(calendar.get("rules"), list):
        raise ConfigError("release_calendar.yaml 的 rules 必须是列表")
    return indicators, sources, calendar
