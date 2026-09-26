"""Read normalized observations with one current version per series."""

from __future__ import annotations

import json
from pathlib import Path

from app.models import DataPoint


def load_period_points(data_root: Path | str, period: str) -> list[DataPoint]:
    """Load a period while ignoring superseded duplicate normalized artifacts.

    Upload history remains available through SQLite. Reports and analysis should
    use one current observation for each indicator and statistical period, so a
    repeated upload cannot inflate a table or an Agent context package.
    """
    root = Path(data_root) / "normalized"
    latest: dict[tuple[str, str], tuple[tuple[str, str], DataPoint]] = {}
    for path in sorted(root.glob(f"*/{period}/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                point = DataPoint(**row)
            except (TypeError, ValueError):
                continue
            key = (point.indicator_id, point.period)
            version = (str(point.retrieved_at or ""), str(path))
            previous = latest.get(key)
            if previous is None or version >= previous[0]:
                latest[key] = (version, point)
    return [item[1] for item in sorted(latest.values(), key=lambda item: (item[1].period, item[1].indicator_id))]
