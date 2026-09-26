from app.models import DataPoint, IndicatorDefinition, VALID_FREQUENCIES, VALID_VALUE_TYPES


def test_allowed_contract_values_are_nonempty():
    assert "monthly" in VALID_FREQUENCIES
    assert "quarterly" in VALID_FREQUENCIES
    assert {"monthly_yoy", "monthly_absolute", "index_level", "stock_yoy"}.issubset(VALID_VALUE_TYPES)


def test_data_point_defaults_are_set():
    point = DataPoint(
        indicator_id="demo",
        indicator_name="示例",
        period="2026-08",
        value=1.2,
        unit="%",
        frequency="monthly",
        source="nbs",
    )
    assert point.revision_status == "original"
    assert point.quality_status == "unverified"


def test_indicator_definition_is_immutable():
    item = IndicatorDefinition(
        indicator_id="demo",
        name="示例",
        theme="production",
        frequency="monthly",
        unit="%",
        value_type="monthly_yoy",
        primary_source="nbs",
    )
    assert item.fallback_sources == ()
    assert item.allow_cumulative is False
    assert item.source_url_field == "source_url"
