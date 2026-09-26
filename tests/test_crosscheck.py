from pathlib import Path

from app.models import DataPoint
from app.pipeline.crosscheck import cross_check_workbook


def test_crosscheck_never_requires_or_writes_missing_workbook(tmp_path: Path):
    point = DataPoint(
        indicator_id="m2_yoy",
        indicator_name="M2货币供应量同比",
        period="2025-08",
        value=8.4,
        unit="%",
        frequency="monthly",
        source="pboc",
    )
    missing = tmp_path / "对齐表.xlsx"
    report = cross_check_workbook([point], missing)
    assert report.status == "workbook_missing"
    assert report.missing == 1
    assert not missing.exists()
