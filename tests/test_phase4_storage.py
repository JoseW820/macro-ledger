import json
import os
from pathlib import Path

from app.models import DataPoint, IndicatorDefinition
from app.providers.international import InternationalProvider
from app.providers.international import fred_fetcher
from app.providers.rates import parse_chinamoney_fdr_csv
from app.providers.official import OfficialResponse
from app.storage.sqlite import SQLiteStore


def indicator():
    return IndicatorDefinition(
        indicator_id="us_fed_funds_rate",
        name="美国联邦基金利率",
        theme="international",
        frequency="monthly",
        unit="%",
        value_type="month_average",
        primary_source="fred",
        definition="美国联邦基金利率月均值",
    )


def test_fred_key_is_required_but_never_persisted(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "secret-test-key")
    provider = InternationalProvider(
        provider_name="fred",
        series_map={"us_fed_funds_rate": "FEDFUNDS"},
        fetcher=lambda indicator, period: OfficialResponse(
            payload={"data": [{"period": period, "value": "5.25", "series": "FEDFUNDS"}]},
            source_url="https://fred.test/series",
            release_date="2025-09-01",
        ),
        data_root=tmp_path,
    )
    result = provider.fetch(indicator(), "2025-08")
    assert result.status == "success"
    raw = Path(result.raw_artifact).read_text(encoding="utf-8")
    assert "secret-test-key" not in raw


def test_rates_rejects_unmarked_dr007_proxy(tmp_path: Path):
    from app.models import IndicatorDefinition
    from app.providers.rates import RatesProvider
    indicator = IndicatorDefinition("dr007_month_average", "DR007月均", "credit", "monthly", "%", "month_average", "rates")
    result = RatesProvider(fetcher=lambda i, p: OfficialResponse({"data": [{"period": p, "value": "1.8", "family": "r007"}]}, "https://rates.test"), data_root=tmp_path).fetch(indicator, "2025-08")
    assert result.status == "definition_mismatch"


def test_fred_fetcher_reads_key_at_call_time(monkeypatch):
    from app.providers import international
    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(international, "json_http_fetcher", lambda url, params: OfficialResponse({"observations": []}, url))
    response = fred_fetcher(series_id="FEDFUNDS")(
        indicator(), "2025-08"
    )
    assert response.payload == {"observations": []}


def test_chinamoney_csv_month_average_is_explicitly_fdr007_fixing():
    raw = b"date,FDR007\n2025-08-01,1.70\n2025-08-04,1.80\n2025-09-01,1.90\n"
    rows = parse_chinamoney_fdr_csv(raw, "2025-08")
    assert rows[0]["value"] == 1.75
    assert rows[0]["family"] == "fdr007_fixing"
    assert rows[0]["is_proxy"] is True


def test_sqlite_keeps_multiple_vintages_and_latest(tmp_path: Path):
    store = SQLiteStore(tmp_path / "macro.sqlite")
    item = IndicatorDefinition(
        indicator_id="m2_yoy", name="M2", theme="credit", frequency="monthly", unit="%", value_type="stock_yoy", primary_source="pboc"
    )
    store.upsert_definition(item, updated_at="2025-09-01T00:00:00Z")
    first = DataPoint("m2_yoy", "M2", "2025-08", 8.4, "%", "monthly", "pboc", retrieved_at="2025-09-15T00:00:00Z")
    revised = DataPoint("m2_yoy", "M2", "2025-08", 8.5, "%", "monthly", "pboc", retrieved_at="2025-10-15T00:00:00Z", revision_status="revised")
    store.insert_points([first], vintage="2025-09-15T00:00:00Z")
    store.insert_points([revised], vintage="2025-10-15T00:00:00Z", reason="official_revision")
    assert store.latest("m2_yoy", "2025-08")["value"] == json.dumps(8.5, ensure_ascii=False)
    assert len(store.history(source="pboc", theme="credit")) == 2
    revision = store.connection.execute("SELECT * FROM revisions").fetchone()
    assert revision["previous_vintage"] == "2025-09-15T00:00:00Z"
    store.close()


def test_sqlite_tracks_run_history(tmp_path: Path):
    store = SQLiteStore(tmp_path / "macro.sqlite")
    run_id = store.run_start("2025-08", "fred", started_at="2025-09-15T00:00:00Z")
    store.run_finish(run_id, status="failed", summary={"error": "network"}, finished_at="2025-09-15T00:01:00Z")
    row = store.runs(period="2025-08")[0]
    assert row["status"] == "failed"
    assert json.loads(row["summary_json"])["error"] == "network"
    store.close()
