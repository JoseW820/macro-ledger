"""Official NBS CSV/JSON file import path for environments where QueryData is blocked."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.models import DataPoint, FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period, parse_numeric, save_normalized_points


class NBSFileProvider:
    source = "nbs_file"

    def __init__(self, *, data_root: Path | str = Path("data")) -> None:
        self.data_root = Path(data_root)

    @staticmethod
    def _read(path: Path) -> tuple[Any, bytes]:
        raw = path.read_bytes()
        if path.suffix.lower() == ".json":
            return json.loads(raw.decode("utf-8-sig")), raw
        text = raw.decode("utf-8-sig")
        return list(csv.DictReader(text.splitlines())), raw

    @staticmethod
    def _rows(payload: Any) -> list[dict[str, Any]]:
        current = payload
        for _ in range(4):
            if not isinstance(current, dict):
                break
            next_value = None
            for key in ("data", "rows", "records", "observations", "results", "items", "list"):
                if key in current:
                    next_value = current[key]
                    break
            if next_value is None or next_value is current:
                break
            current = next_value
        if isinstance(current, dict):
            current = [current]
        return [row for row in current if isinstance(row, dict)] if isinstance(current, list) else []

    def fetch(self, indicator: IndicatorDefinition, period: str, file_path: Path | str) -> FetchResult:
        path = Path(file_path)
        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        if not path.exists():
            return FetchResult(indicator=indicator, period=period, status="not_published", errors=[f"官方文件不存在: {path}"])
        try:
            payload, raw = self._read(path)
        except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
            return FetchResult(indicator=indicator, period=period, status="parse_error", errors=[str(exc)])
        digest = hashlib.sha256(raw).hexdigest()
        raw_dir = self.data_root / "raw" / "nbs_file" / indicator.indicator_id / period
        raw_dir.mkdir(parents=True, exist_ok=True)
        artifact = raw_dir / f"{digest}.json"
        artifact.write_text(json.dumps({"source_file": str(path), "sha256": digest, "retrieved_at": retrieved_at, "definition": indicator.__dict__, "response": payload}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        points: list[DataPoint] = []
        try:
            for row in self._rows(payload):
                row_period = row.get("period", row.get("date", row.get("time", row.get("dt"))))
                if not row_period or normalize_period(row_period, indicator.frequency) != period:
                    continue
                region = str(row.get("region", row.get("area", row.get("da_name", "全国")))).strip()
                if region not in {"全国", "中国", "China", "national", ""}:
                    continue
                value = parse_numeric(row.get("value", row.get("data")))
                if value is None:
                    continue
                # The configured indicator contract is authoritative. Older
                # workbooks may carry a generic '%' column even for fiscal
                # cumulative amounts; store the configured unit instead.
                points.append(DataPoint(indicator_id=indicator.indicator_id, indicator_name=indicator.name, period=period, value=value, unit=indicator.unit, frequency=indicator.frequency, source=self.source, source_url=str(path), release_date=row.get("release_date"), retrieved_at=retrieved_at, definition=indicator.definition, calculation_method="official_file", quality_status="unverified"))
        except (NormalizationError, ValueError) as exc:
            return FetchResult(indicator=indicator, period=period, raw_artifact=str(artifact), status="definition_mismatch", errors=[str(exc)], metadata={"sha256": digest})
        if not points:
            return FetchResult(indicator=indicator, period=period, raw_artifact=str(artifact), status="no_data", errors=["官方文件没有匹配的全国统计期数据"], metadata={"sha256": digest})
        normalized = save_normalized_points(points, self.data_root / "normalized")
        return FetchResult(indicator=indicator, period=period, points=points, raw_artifact=str(artifact), status="success", metadata={"sha256": digest, "normalized_artifact": str(normalized), "source_file": str(path)})
