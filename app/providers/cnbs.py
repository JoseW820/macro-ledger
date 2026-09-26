"""Optional adapter for the cnbs MCP capability.

The open-source project cannot assume Codex's local MCP configuration. A host
application can inject a small client implementing ``fetch`` (and optionally
``search``); when it is absent this provider reports ``provider_unavailable``
instead of pretending that data was collected.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
import json

from app.models import DataPoint, FetchResult, IndicatorDefinition
from app.pipeline.normalize import parse_numeric, normalize_period, save_normalized_points


class CnbsClient(Protocol):
    def fetch(self, *, indicator: IndicatorDefinition, period: str) -> Any: ...

    def search(self, *, query: str) -> Any: ...


class CnbsProvider:
    """Translate an injected cnbs client response into project contracts."""

    def __init__(self, client: CnbsClient | None = None, *, data_root: Path | str = Path("data")) -> None:
        self.client = client
        self.data_root = Path(data_root)

    def search(self, query: str) -> list[dict[str, Any]]:
        if self.client is None:
            return []
        result = self.client.search(query=query)
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        if isinstance(result, dict):
            candidates = result.get("data", result.get("results", result.get("items", [])))
            if isinstance(candidates, list):
                return [item for item in candidates if isinstance(item, dict)]
        return []

    def _save_raw(self, indicator: IndicatorDefinition, period: str, payload: Any, retrieved_at: str) -> str:
        directory = self.data_root / "raw" / "cnbs" / indicator.indicator_id / period
        directory.mkdir(parents=True, exist_ok=True)
        stamp = retrieved_at.replace("+00:00", "Z").replace(":", "")
        target = directory / f"{stamp}.json"
        suffix = 1
        while target.exists():
            target = directory / f"{stamp}_{suffix}.json"
            suffix += 1
        target.write_text(
            json.dumps(
                {
                    "retrieved_at": retrieved_at,
                    "request": {"indicator_id": indicator.indicator_id, "period": period},
                    "definition": asdict(indicator),
                    "response": payload,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return str(target)

    @staticmethod
    def _to_points(indicator: IndicatorDefinition, period: str, payload: Any, retrieved_at: str) -> list[DataPoint]:
        rows = payload
        if isinstance(payload, dict):
            # MCP results may be wrapped as structuredContent.results.data.data.
            for wrapper in ("structuredContent", "results"):
                if isinstance(payload.get(wrapper), dict):
                    payload = payload[wrapper]
            if isinstance(payload.get("data"), dict) and isinstance(payload["data"].get("data"), list):
                rows = payload["data"]["data"]
            else:
                rows = payload.get("data", payload.get("observations", payload.get("results", payload.get("items", []))))
                if isinstance(rows, dict):
                    rows = rows.get("data", rows.get("observations", rows.get("results", rows.get("list", rows))))
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            return []
        points: list[DataPoint] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_period = row.get("period", row.get("date", row.get("time", row.get("dt", period))))
            try:
                normalized_period = normalize_period(raw_period, indicator.frequency)
            except ValueError:
                continue
            if normalized_period != period:
                continue
            region = str(row.get("da_name", row.get("region", row.get("area", "全国")))).strip()
            if region and region not in {"全国", "中国", "China", "national"}:
                continue
            value = parse_numeric(row.get("value", row.get("data")))
            if value is None:
                continue
            unit = row.get("unit", row.get("du_name", indicator.unit))
            source_url = row.get("source_url") or row.get("treeinfo_globalid")
            release_date = row.get("release_date") or row.get("dt_name")
            points.append(
                DataPoint(
                    indicator_id=indicator.indicator_id,
                    indicator_name=indicator.name,
                    period=period,
                    value=value,
                    unit=str(unit),
                    frequency=indicator.frequency,
                    source="cnbs",
                    source_url=source_url,
                    release_date=release_date,
                    retrieved_at=retrieved_at,
                    definition=indicator.definition,
                    calculation_method="cnbs_observation",
                    quality_status="unverified",
                )
            )
        return points

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self.client is None:
            return FetchResult(
                indicator=indicator,
                period=period,
                status="provider_unavailable",
                errors=["cnbs 客户端未注入；开源项目不依赖 Codex 本机 MCP 配置"],
            )
        try:
            payload = self.client.fetch(indicator=indicator, period=period)
            raw_artifact = self._save_raw(indicator, period, payload, retrieved_at)
            points = self._to_points(indicator, period, payload, retrieved_at)
            if not points:
                return FetchResult(indicator=indicator, period=period, raw_artifact=raw_artifact, status="no_data", errors=["cnbs 返回空数据或统计期不匹配"])
            normalized_path = save_normalized_points(points, self.data_root / "normalized")
            return FetchResult(
                indicator=indicator,
                period=period,
                points=points,
                raw_artifact=raw_artifact,
                status="success",
                metadata={"normalized_artifact": str(normalized_path)},
            )
        except Exception as exc:  # client implementations vary; preserve a typed result for the pipeline
            return FetchResult(indicator=indicator, period=period, status="interface_error", errors=[str(exc)])

    def fetch_search_payload(self, indicator: IndicatorDefinition, period: str, payload: Any) -> FetchResult:
        """Adapt a direct cnbs search/fetch_data_from_source payload."""
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        raw_artifact = self._save_raw(indicator, period, payload, retrieved_at)
        points = self._to_points(indicator, period, payload, retrieved_at)
        if not points:
            return FetchResult(indicator=indicator, period=period, raw_artifact=raw_artifact, status="no_data", errors=["cnbs 响应未找到全国且统计期匹配的数据"])
        normalized_path = save_normalized_points(points, self.data_root / "normalized")
        return FetchResult(indicator=indicator, period=period, points=points, raw_artifact=raw_artifact, status="success", metadata={"normalized_artifact": str(normalized_path)})
