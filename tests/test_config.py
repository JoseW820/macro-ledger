from pathlib import Path

from app.config import load_confirmed_nbs_codes, load_indicators, validate_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def test_project_config_is_valid():
    indicators, sources, calendar = validate_config(CONFIG)
    assert len(indicators) >= 15
    assert "nbs" in sources
    assert calendar["rules"]


def test_core_indicators_cover_four_homepage_dimensions():
    indicators = load_indicators(CONFIG)
    themes = {item.theme for item in indicators if item.homepage_core}
    assert {"production", "demand", "prices", "credit"}.issubset(themes)


def test_indicator_contract_includes_release_and_traceability_fields():
    indicators = load_indicators(CONFIG)
    assert all(item.release_description for item in indicators)
    assert all(item.source_url_field for item in indicators)
    assert any(item.allow_cumulative for item in indicators)


def test_confirmed_nbs_codes_are_separate_from_indicator_config():
    codes = load_confirmed_nbs_codes(CONFIG)
    assert codes["pmi_manufacturing"]["frequency"] == "monthly"
    assert codes["industrial_value_added_yoy"]["geography"] == "全国"


def test_trade_totals_use_nbs_with_cnbs_fallback():
    indicators = {item.indicator_id: item for item in load_indicators(CONFIG)}
    for name in ("exports_rmb_monthly", "imports_rmb_monthly", "trade_balance_rmb_monthly"):
        assert indicators[name].primary_source == "nbs"
        assert indicators[name].fallback_sources == ("cnbs",)
