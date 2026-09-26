"""Optional FRED/IMF/World Bank/BIS/OECD adapter with environment-only secrets."""

from __future__ import annotations

import os
from urllib.parse import urlencode
from .official import json_http_fetcher
from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period
from .official import OfficialProviderBase, OfficialResponse, make_point, payload_rows, payload_shape_is_valid, response_status, save_official_artifact


class InternationalProvider(OfficialProviderBase):
    source = "international"

    def __init__(self, *, provider_name: str = "fred", series_map=None, api_key_env: str = "FRED_API_KEY", **kwargs):
        super().__init__(**kwargs)
        self.provider_name = provider_name
        self.series_map = dict(series_map or {})
        self.api_key_env = api_key_env

    def _failure(self, indicator, period, response, status, message):
        artifact, digest = save_official_artifact(source=self.source, indicator=indicator, period=period, response=response, root=self.data_root)
        return FetchResult(indicator=indicator, period=period, raw_artifact=artifact, status=status, errors=[message], metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url})

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        if self.provider_name == "fred" and not os.getenv(self.api_key_env):
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[f"{self.api_key_env} 未设置；密钥只从环境变量读取"])
        if self.fetcher is None:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[f"{self.provider_name} fetcher 未配置"])
        try:
            response = self._fetch_response(indicator, period)
        except LookupError as exc:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[str(exc)])
        except OSError as exc:
            return FetchResult(indicator=indicator, period=period, status="network_error", errors=[str(exc)])
        status = response_status(response.payload)
        if status:
            return self._failure(indicator, period, response, status, f"{self.provider_name} 来源状态: {status}")
        if not payload_shape_is_valid(response.payload):
            return self._failure(indicator, period, response, "parse_error", f"{self.provider_name} 响应结构无法解析")
        points = []
        try:
            for row in payload_rows(response.payload):
                if normalize_period(row.get("period", row.get("date", row.get("time", period))), indicator.frequency) != period:
                    continue
                series = str(row.get("series", row.get("series_id", ""))).strip()
                expected = self.series_map.get(indicator.indicator_id)
                if expected and series and series != expected:
                    raise ValueError(f"国际序列不匹配：需要 {expected}，收到 {series}")
                points.append(make_point(source=self.source, indicator=indicator, row=row, period=period, response=response, value=row.get("value", row.get("data"))))
        except (NormalizationError, ValueError) as exc:
            return self._failure(indicator, period, response, "definition_mismatch", str(exc))
        if not points:
            return self._failure(indicator, period, response, "not_published", f"{self.provider_name} 尚未发布该统计期数据")
        return self._finish(indicator=indicator, period=period, response=response, points=points)


def fred_fetcher(*, series_id: str, api_key_env: str = "FRED_API_KEY", base_url: str = "https://api.stlouisfed.org/fred/series/observations"):
    """Create a FRED fetcher; the key is read only at call time and never returned."""
    def fetch(indicator: IndicatorDefinition, period: str) -> OfficialResponse:
        key = os.getenv(api_key_env)
        if not key:
            raise LookupError(f"{api_key_env} 未设置")
        return json_http_fetcher(base_url, params={"series_id": series_id, "api_key": key, "file_type": "json", "observation_start": f"{period}-01", "observation_end": f"{period}-28"})
    return fetch


FRED_SERIES_MAP = {
    "us_fed_funds_rate": "FEDFUNDS",
    "us_10y_treasury_yield": "DGS10",
    "dollar_index": "DTWEXBGS",
}
