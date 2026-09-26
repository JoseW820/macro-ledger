from app.models import FetchResult, IndicatorDefinition
from app.pipeline.fetch import ProviderRegistry, fetch_one


class FailingProvider:
    def fetch(self, indicator, period):
        return FetchResult(indicator=indicator, period=period, status="no_data", errors=["无数据"])


class WorkingProvider:
    def fetch(self, indicator, period):
        from app.models import DataPoint

        point = DataPoint(
            indicator_id=indicator.indicator_id,
            indicator_name=indicator.name,
            period=period,
            value=1.0,
            unit=indicator.unit,
            frequency=indicator.frequency,
            source="cnbs",
        )
        return FetchResult(indicator=indicator, period=period, points=[point], status="success")


def test_pipeline_uses_explicit_fallback_and_records_attempts(tmp_path):
    indicator = IndicatorDefinition(
        indicator_id="demo",
        name="示例",
        theme="production",
        frequency="monthly",
        unit="%",
        value_type="monthly_yoy",
        primary_source="nbs",
        fallback_sources=("cnbs",),
    )
    result = fetch_one(
        indicator,
        "2025-08",
        ProviderRegistry({"nbs": FailingProvider(), "cnbs": WorkingProvider()}),
        normalized_root=tmp_path / "normalized",
    )
    assert result.status == "success"
    assert [item["provider"] for item in result.metadata["attempts"]] == ["nbs", "cnbs"]
    assert result.metadata["normalized_artifact"]
