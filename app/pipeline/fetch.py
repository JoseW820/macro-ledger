"""Provider orchestration for one monthly collection run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.models import DataPoint, FetchResult, IndicatorDefinition, QualityIssue, RunSummary
from app.pipeline.normalize import save_normalized_points


class Provider(Protocol):
    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult: ...


@dataclass
class ProviderRegistry:
    providers: dict[str, Provider]

    def get(self, name: str) -> Provider | None:
        return self.providers.get(name)


FALLBACK_STATUSES = {
    "transport_error",
    "interface_error",
    "indicator_not_found",
    "no_data",
    "provider_unavailable",
}


def fetch_one(
    indicator: IndicatorDefinition,
    period: str,
    registry: ProviderRegistry,
    *,
    normalized_root: Path | str = Path("data/normalized"),
) -> FetchResult:
    """Try the configured primary and then explicit fallback providers."""

    provider_names = (indicator.primary_source, *indicator.fallback_sources)
    attempts: list[dict[str, Any]] = []
    last_result = FetchResult(indicator=indicator, period=period, status="provider_unavailable")
    for index, provider_name in enumerate(provider_names):
        provider = registry.get(provider_name)
        if provider is None:
            attempts.append({"provider": provider_name, "status": "provider_unavailable"})
            last_result = FetchResult(
                indicator=indicator,
                period=period,
                status="provider_unavailable",
                errors=[f"未注册 Provider: {provider_name}"],
            )
            continue
        result = provider.fetch(indicator, period)
        attempts.append({"provider": provider_name, "status": result.status, "errors": result.errors})
        result.metadata.setdefault("attempts", attempts)
        if result.status == "success":
            if result.points and not result.metadata.get("normalized_artifact"):
                path = save_normalized_points(result.points, Path(normalized_root))
                result.metadata["normalized_artifact"] = str(path)
            return result
        last_result = result
        if result.status not in FALLBACK_STATUSES:
            break
        if index == len(provider_names) - 1:
            break
    last_result.metadata.setdefault("attempts", attempts)
    return last_result


def fetch_indicators(
    indicators: list[IndicatorDefinition],
    period: str,
    registry: ProviderRegistry,
    *,
    normalized_root: Path | str = Path("data/normalized"),
) -> tuple[list[FetchResult], RunSummary]:
    """Collect all configured indicators and summarize failures as issues."""

    results: list[FetchResult] = []
    issues: list[QualityIssue] = []
    completed = 0
    failed = 0
    for indicator in indicators:
        result = fetch_one(indicator, period, registry, normalized_root=normalized_root)
        results.append(result)
        if result.status == "success":
            completed += 1
        else:
            failed += 1
            issues.append(
                QualityIssue(
                    code=result.status,
                    message="；".join(result.errors) or "采集失败",
                    indicator_id=indicator.indicator_id,
                    period=period,
                    severity="error",
                )
            )
    return results, RunSummary(
        period=period,
        dry_run=False,
        planned_indicators=len(indicators),
        completed=completed,
        failed=failed,
        issues=issues,
    )
