import json
from pathlib import Path

import pytest

from app.models import IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_nbs_payload, parse_numeric, save_normalized_points
from app.providers.nbs import HttpResponse, NBSProvider


def indicator(**overrides):
    values = dict(
        indicator_id="cpi_yoy",
        name="居民消费价格指数同比",
        theme="prices",
        frequency="monthly",
        unit="%",
        value_type="monthly_yoy",
        primary_source="nbs",
        fallback_sources=(),
        allow_cumulative=False,
        release_description="次月发布",
        source_url_field="official_release_url",
        homepage_core=True,
        definition="全国居民消费价格相对于上年同月的变化",
    )
    values.update(overrides)
    return IndicatorDefinition(**values)


def payload(value="0.7"):
    return {
        "returncode": 0,
        "returndata": {
            "datanodes": [
                {
                    "code": "A010101_202508",
                    "wds": [
                        {"wdcode": "zb", "valuecode": "A010101", "value": "居民消费价格指数同比"},
                        {"wdcode": "sj", "valuecode": "202508", "value": "2025年08月"},
                        {"wdcode": "reg", "valuecode": "00", "value": "全国"},
                    ],
                    "data": {"data": value, "hasdata": True},
                },
                {
                    "code": "A010101_202508_local",
                    "wds": [
                        {"wdcode": "sj", "valuecode": "202508"},
                        {"wdcode": "reg", "valuecode": "110000", "value": "北京市"},
                    ],
                    "data": {"data": "99", "hasdata": True},
                },
            ]
        },
    }


def test_normalize_nbs_payload_keeps_national_observation_only():
    points = normalize_nbs_payload(payload(), indicator(), "2025-08", "https://example.test")
    assert len(points) == 1
    assert points[0].value == 0.7
    assert points[0].period == "2025-08"
    assert points[0].source == "nbs"
    assert points[0].quality_status == "unverified"


def test_cumulative_definition_is_rejected_for_monthly_yoy():
    bad = payload()
    bad["returndata"]["name"] = "居民消费价格指数累计同比"
    with pytest.raises(NormalizationError):
        normalize_nbs_payload(bad, indicator(), "2025-08", "https://example.test")


def test_numeric_parser_handles_missing_and_commas():
    assert parse_numeric("1,234.50") == 1234.5
    assert parse_numeric("-") is None
    assert parse_numeric("abc") == "abc"


def test_nbs_provider_saves_raw_and_normalized_artifacts(tmp_path: Path):
    response = HttpResponse(200, json.dumps(payload()).encode("utf-8"), {})

    def fake_get(url, params, timeout):
        assert params["m"] == "QueryData"
        return response

    provider = NBSProvider(
        code_map={"cpi_yoy": "A010101"},
        data_root=tmp_path,
        http_get=fake_get,
        sleep=lambda _: None,
    )
    result = provider.fetch(indicator(), "2025-08")
    assert result.status == "success"
    assert result.points[0].value == 0.7
    assert Path(result.raw_artifact, "response.json").exists()
    normalized = save_normalized_points(result.points, tmp_path / "normalized")
    assert normalized.exists()


def test_nbs_provider_distinguishes_missing_code(tmp_path: Path):
    result = NBSProvider(data_root=tmp_path).fetch(indicator(), "2025-08")
    assert result.status == "indicator_not_found"
    assert "代码" in result.errors[0]


def test_nbs_provider_fetches_history_without_splitting_periods(tmp_path: Path):
    history = payload()
    first = history["returndata"]["datanodes"][0]
    second = json.loads(json.dumps(first))
    second["code"] = "A010101_202507"
    second["wds"][1] = {"wdcode": "sj", "valuecode": "202507", "value": "2025年07月"}
    second["data"]["data"] = "0.6"
    history["returndata"]["datanodes"].append(second)
    response = HttpResponse(200, json.dumps(history).encode("utf-8"), {})
    provider = NBSProvider(
        code_map={"cpi_yoy": "A010101"},
        data_root=tmp_path,
        http_get=lambda url, params, timeout: response,
        sleep=lambda _: None,
    )
    result = provider.fetch_history(indicator(), start_period="2025-07", end_period="2025-08")
    assert result.status == "success"
    assert [point.period for point in result.points] == ["2025-08", "2025-07"]
    assert Path(result.metadata["normalized_artifact"]).exists()
