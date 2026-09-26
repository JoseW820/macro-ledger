import json
from pathlib import Path

from app.pipeline.normalized import load_period_points


def _point(value: float, retrieved_at: str) -> dict[str, object]:
    return {
        "indicator_id": "cpi_yoy",
        "indicator_name": "CPI",
        "period": "2026-07",
        "value": value,
        "unit": "%",
        "frequency": "monthly",
        "source": "nbs",
        "retrieved_at": retrieved_at,
        "definition": "同比",
        "calculation_method": "official_file",
        "revision_status": "original",
        "quality_status": "unverified",
    }


def test_loader_keeps_latest_version_per_indicator_period(tmp_path: Path):
    root = tmp_path / "normalized" / "cpi_yoy" / "2026-07"
    root.mkdir(parents=True)
    (root / "old.json").write_text(json.dumps([_point(0.2, "2026-09-25T04:00:00+00:00")]), encoding="utf-8")
    (root / "new.json").write_text(json.dumps([_point(0.3, "2026-09-25T04:05:00+00:00")]), encoding="utf-8")

    points = load_period_points(tmp_path, "2026-07")

    assert len(points) == 1
    assert points[0].value == 0.3
