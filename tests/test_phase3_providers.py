from pathlib import Path

from app.models import IndicatorDefinition
from app.providers.customs import CustomsProvider
from app.providers.mof import MOFProvider
from app.providers.official import OfficialResponse
from app.providers.pboc import PBOCProvider
from app.providers.safe import SAFEProvider
from app.providers.safe import parse_safe_article


def make_indicator(indicator_id, name, frequency="monthly", unit="%", value_type="monthly_yoy", source="pboc"):
    return IndicatorDefinition(
        indicator_id=indicator_id,
        name=name,
        theme="credit",
        frequency=frequency,
        unit=unit,
        value_type=value_type,
        primary_source=source,
        release_description="官方发布",
        source_url_field="official_release_url",
        definition=name,
    )


def fake_fetch(payload, source_url="https://official.test/data", release_date="2025-09-15"):
    return lambda indicator, period: OfficialResponse(payload=payload, source_url=source_url, release_date=release_date)


def test_pboc_m2_keeps_stock_yoy_semantics_and_audit_metadata(tmp_path: Path):
    indicator = make_indicator("m2_yoy", "M2货币供应量同比", value_type="stock_yoy")
    provider = PBOCProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "8.4", "series": "m2", "currency": "CNY", "measure": "stock_yoy"}]}),
        data_root=tmp_path,
    )
    result = provider.fetch(indicator, "2025-08")
    assert result.status == "success"
    assert result.points[0].source == "pboc"
    assert result.metadata["release_date"] == "2025-09-15"
    assert len(result.metadata["sha256"]) == 64
    assert Path(result.raw_artifact).exists()


def test_pboc_rejects_increment_for_stock_indicator(tmp_path: Path):
    indicator = make_indicator("m2_yoy", "M2货币供应量同比", value_type="stock_yoy")
    provider = PBOCProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "100", "series": "m2", "measure": "increment"}]}),
        data_root=tmp_path,
    )
    assert provider.fetch(indicator, "2025-08").status == "definition_mismatch"


def test_customs_rejects_bilateral_trade_and_accepts_national_rmb(tmp_path: Path):
    indicator = make_indicator("exports_rmb_monthly", "出口额当月值", unit="亿元人民币", value_type="monthly_absolute", source="customs")
    good = CustomsProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "22000", "scope": "全国", "partner": "全国", "currency": "CNY", "measure": "amount"}]}),
        data_root=tmp_path / "good",
    ).fetch(indicator, "2025-08")
    assert good.status == "success"
    bad = CustomsProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "22000", "scope": "全国", "partner": "印度", "currency": "CNY"}]}),
        data_root=tmp_path / "bad",
    ).fetch(indicator, "2025-08")
    assert bad.status == "definition_mismatch"


def test_safe_separates_settlement_from_balance_of_payments(tmp_path: Path):
    settlement = make_indicator("bank_settlement_balance_usd", "银行结售汇差额", unit="亿美元", value_type="monthly_absolute", source="safe")
    provider = SAFEProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "12.3", "series": "bank_settlement", "currency": "USD"}]}),
        data_root=tmp_path,
    )
    assert provider.fetch(settlement, "2025-08").status == "success"

    current_account = make_indicator("international_balance_current_account", "国际收支经常账户差额", frequency="quarterly", unit="亿美元", value_type="quarterly_absolute", source="safe")
    result = SAFEProvider(
        fetcher=fake_fetch({"data": [{"period": "2025年第二季度", "value": "30", "series": "balance_of_payments", "currency": "USD"}]}),
        data_root=tmp_path / "bop",
    ).fetch(current_account, "2025-Q2")
    assert result.status == "success"

    wrong = SAFEProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "12.3", "series": "cross_border_receipts_payments", "currency": "USD"}]}),
        data_root=tmp_path / "wrong",
    ).fetch(settlement, "2025-08")
    assert wrong.status == "definition_mismatch"


def test_mof_distinguishes_general_budget_from_government_fund(tmp_path: Path):
    indicator = make_indicator("general_public_budget_revenue_ytd_yoy", "全国一般公共预算收入累计同比", unit="%", value_type="ytd_yoy", source="mof")
    good = MOFProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "3.2", "budget_type": "general_public_budget", "measure": "ytd_yoy"}]}),
        data_root=tmp_path,
    ).fetch(indicator, "2025-08")
    assert good.status == "success"
    bad = MOFProvider(
        fetcher=fake_fetch({"data": [{"period": "2025-08", "value": "3.2", "budget_type": "government_fund_budget", "measure": "ytd_yoy"}]}),
        data_root=tmp_path / "bad",
    ).fetch(indicator, "2025-08")
    assert bad.status == "definition_mismatch"


def test_official_provider_preserves_not_published_status(tmp_path: Path):
    indicator = make_indicator("m2_yoy", "M2货币供应量同比", value_type="stock_yoy")
    result = PBOCProvider(fetcher=fake_fetch({"status": "not_published"}), data_root=tmp_path).fetch(indicator, "2025-08")
    assert result.status == "not_published"


def test_safe_article_parser_keeps_settlement_and_cross_border_series_separate():
    html = "<p>2025年8月，银行结汇17090亿元人民币，售汇13800亿元人民币。</p><p>2025年8月，银行代客涉外收入52718亿元人民币，对外付款48486亿元人民币。</p>"
    rows = parse_safe_article(html, "2025-08")
    assert {row["series"] for row in rows} == {"bank_settlement", "cross_border_receipts_payments"}
    assert next(row["value"] for row in rows if row["series"] == "bank_settlement") == 3290
