import json
from pathlib import Path

from app.models import IndicatorDefinition
from app.providers.customs import CustomsProvider
from app.providers.mof import MOFProvider
from app.providers.official import OfficialResponse, configured_endpoint_fetcher
from app.providers.pboc import PBOCProvider
from app.providers.safe import SAFEProvider


def item(indicator_id, name, unit="%", value_type="monthly_yoy", source="pboc"):
    return IndicatorDefinition(indicator_id, name, "test", "monthly", unit, value_type, source, definition=name)


def response(payload):
    return OfficialResponse(payload, "https://official.example/data", "2025-09-15")


def test_all_four_providers_accept_official_json_shape(tmp_path):
    pboc = PBOCProvider(fetcher=lambda i, p: response({"data": [{"period": p, "value": "8.4", "series": "m2", "measure": "stock_yoy", "currency": "CNY"}]}), data_root=tmp_path)
    assert pboc.fetch(item("m2_yoy", "M2货币供应量同比", source="pboc"), "2025-08").status == "success"

    customs = CustomsProvider(fetcher=lambda i, p: response({"data": [{"period": p, "value": "22000", "scope": "全国", "partner": "全国", "currency": "CNY", "measure": "amount"}]}), data_root=tmp_path)
    assert customs.fetch(item("exports_rmb_monthly", "出口额当月值", unit="亿元人民币", value_type="monthly_absolute", source="customs"), "2025-08").status == "success"

    safe = SAFEProvider(fetcher=lambda i, p: response({"data": [{"period": p, "value": "12.3", "series": "bank_settlement", "currency": "USD"}]}), data_root=tmp_path)
    assert safe.fetch(item("bank_settlement_balance_usd", "银行结售汇差额", unit="亿美元", value_type="monthly_absolute", source="safe"), "2025-08").status == "success"

    mof = MOFProvider(fetcher=lambda i, p: response({"data": [{"period": p, "value": "3.2", "budget_type": "general_public_budget", "measure": "ytd_yoy"}]}), data_root=tmp_path)
    assert mof.fetch(item("general_public_budget_revenue_ytd_yoy", "全国一般公共预算收入累计同比", value_type="ytd_yoy", source="mof"), "2025-08").status == "success"


def test_endpoint_fetcher_reads_only_environment(monkeypatch, tmp_path):
    payload = tmp_path / "official.json"
    payload.write_text(json.dumps({"data": []}), encoding="utf-8")
    monkeypatch.setenv("TEST_OFFICIAL_ENDPOINT", payload.as_uri())
    fetcher = configured_endpoint_fetcher("TEST_OFFICIAL_ENDPOINT")
    result = fetcher(item("m2_yoy", "M2", source="pboc"), "2025-08")
    assert result.payload == {"data": []}
    monkeypatch.delenv("TEST_OFFICIAL_ENDPOINT")
