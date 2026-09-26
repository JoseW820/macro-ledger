from pathlib import Path

from app.models import IndicatorDefinition
from app.providers.cnbs import CnbsProvider


class FakeCnbs:
    def fetch(self, *, indicator, period):
        return {
            "data": {
                "data": [
                    {"dt": "202508", "value": "49.8", "da_name": "全国", "unit": "%"},
                    {"dt": "202508", "value": "50.1", "da_name": "北京市", "unit": "%"},
                ]
            }
        }

    def search(self, *, query):
        return [{"name": query, "setId": "demo"}]


def test_cnbs_adapter_normalizes_search_style_rows(tmp_path: Path):
    indicator = IndicatorDefinition(
        indicator_id="pmi_manufacturing",
        name="制造业采购经理指数",
        theme="production",
        frequency="monthly",
        unit="index",
        value_type="index_level",
        primary_source="nbs",
        allow_cumulative=False,
        release_description="月末发布",
        source_url_field="official_release_url",
    )
    result = CnbsProvider(FakeCnbs(), data_root=tmp_path).fetch(indicator, "2025-08")
    assert result.status == "success"
    assert len(result.points) == 1
    assert result.points[0].value == 49.8
    assert Path(result.raw_artifact).exists()


def test_cnbs_without_client_is_explicitly_unavailable():
    indicator = IndicatorDefinition(
        indicator_id="demo",
        name="示例",
        theme="production",
        frequency="monthly",
        unit="%",
        value_type="monthly_yoy",
        primary_source="cnbs",
    )
    result = CnbsProvider().fetch(indicator, "2025-08")
    assert result.status == "provider_unavailable"


def test_cnbs_actual_search_payload_shape_is_normalized(tmp_path: Path):
    indicator = IndicatorDefinition(
        indicator_id="industrial_value_added_yoy",
        name="规上工业增加值同比",
        theme="production",
        frequency="monthly",
        unit="%",
        value_type="monthly_yoy",
        primary_source="nbs",
        allow_cumulative=False,
        release_description="国家统计局发布",
        source_url_field="official_release_url",
    )
    payload = {
        "structuredContent": {
            "data": {
                "data": [
                    {"indic_id": "ef1b1765960d45a29b4d7c4ca91be916", "dt": "202508", "dt_name": "2025年8月", "da_name": "全国", "value": "5.2", "show_name": "规上工业增加值同比增长 (%)", "treeinfo_globalid": "series-id"},
                    {"indic_id": "ef1b1765960d45a29b4d7c4ca91be916", "dt": "202508", "dt_name": "2025年8月", "da_name": "北京市", "value": "99", "show_name": "规上工业增加值同比增长 (%)"},
                ]
            }
        }
    }
    result = CnbsProvider(data_root=tmp_path).fetch_search_payload(indicator, "2025-08", payload)
    assert result.status == "success"
    assert len(result.points) == 1
    assert result.points[0].value == 5.2
    assert result.points[0].source_url == "series-id"
    assert Path(result.raw_artifact).exists()
