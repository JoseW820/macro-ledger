import json
from pathlib import Path

from app.models import IndicatorDefinition
from app.providers.nbs_file import NBSFileProvider


def indicator(**overrides):
    values = dict(
        indicator_id="industrial_value_added_yoy",
        name="规上工业增加值同比",
        theme="production",
        frequency="monthly",
        unit="%",
        value_type="monthly_yoy",
        primary_source="nbs",
        fallback_sources=(),
        allow_cumulative=False,
        release_description="次月发布",
        source_url_field="official_release_url",
        homepage_core=True,
        definition="全国规上工业增加值同比",
    )
    values.update(overrides)
    return IndicatorDefinition(**values)


def test_csv_import_keeps_national_row_and_artifacts(tmp_path: Path):
    source = tmp_path / "official.csv"
    source.write_text(
        "period,region,value,unit\n2025年08月,全国,4.5,%\n2025年08月,北京市,1.0,%\n",
        encoding="utf-8",
    )
    result = NBSFileProvider(data_root=tmp_path / "data").fetch(indicator(), "2025-08", source)
    assert result.status == "success"
    assert len(result.points) == 1
    assert result.points[0].value == 4.5
    assert Path(result.raw_artifact).exists()
    assert Path(result.metadata["normalized_artifact"]).exists()


def test_json_wrappers_and_missing_file(tmp_path: Path):
    source = tmp_path / "official.json"
    source.write_text(json.dumps({"data": {"rows": [{"date": "2025-08", "area": "全国", "data": "2.1"}]}}), encoding="utf-8")
    result = NBSFileProvider(data_root=tmp_path / "data").fetch(indicator(), "2025-08", source)
    assert result.status == "success"
    assert result.points[0].value == 2.1

    missing = NBSFileProvider(data_root=tmp_path / "data").fetch(indicator(), "2025-08", tmp_path / "missing.csv")
    assert missing.status == "not_published"


def test_period_mismatch_and_no_data_are_explicit(tmp_path: Path):
    source = tmp_path / "official.csv"
    source.write_text("period,region,value\n2025-07,全国,4.5\n", encoding="utf-8")
    result = NBSFileProvider(data_root=tmp_path / "data").fetch(indicator(), "2025-08", source)
    assert result.status == "no_data"

