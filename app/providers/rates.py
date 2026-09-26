"""China Money/ChinaBond provider for FX, bond yields and interbank rates."""

from __future__ import annotations

from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period
from .official import OfficialProviderBase, OfficialResponse, make_point, payload_rows, payload_shape_is_valid, response_status, save_official_artifact
from .official import file_or_json_fetcher
import csv
import io
from datetime import datetime


def chinamoney_repo_fetcher(url: str = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/currency/fdr-chrt.csv"):
    """Fetch the official ChinaMoney fixing CSV used by open-source collectors."""
    def fetch(indicator: IndicatorDefinition, period: str) -> OfficialResponse:
        return file_or_json_fetcher(url)
    return fetch


def parse_chinamoney_fdr_csv(raw: bytes, period: str) -> list[dict[str, object]]:
    text = raw.decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    values: list[float] = []
    for row in rows:
        date = row.get("date") or row.get("Date") or row.get("tradeDate") or row.get("日期")
        if not date or str(date)[:7].replace("/", "-") != period:
            continue
        value = row.get("FDR007") or row.get("fdr007") or row.get("FDR007加权")
        try:
            values.append(float(str(value).replace(",", "")))
        except (TypeError, ValueError):
            continue
    if not values:
        return []
    return [{"period": period, "value": sum(values) / len(values), "family": "fdr007_fixing", "unit": "%", "observation_count": len(values), "is_proxy": True}]


class RatesProvider(OfficialProviderBase):
    source = "rates"

    _families = {
        "cny_usd_month_end": "cny_fixing",
        "cny_usd_month_average": "cny_fixing",
        "china_10y_gov_yield": "gov_yield",
        "china_10y_gov_yield_month_end": "gov_yield",
        "dr007_month_average": "dr007",
        "repo_7d_month_average": "repo_7d",
    }

    _proxies = {"dr007_month_average": {"shibor_1w", "r007"}}

    def _failure(self, indicator, period, response, status, message):
        artifact, digest = save_official_artifact(source=self.source, indicator=indicator, period=period, response=response, root=self.data_root)
        return FetchResult(indicator=indicator, period=period, raw_artifact=artifact, status=status, errors=[message], metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url})

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        if self.fetcher is None:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=["利率/汇率官方 fetcher 未配置"])
        try:
            response = self._fetch_response(indicator, period)
        except LookupError as exc:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[str(exc)])
        except OSError as exc:
            return FetchResult(indicator=indicator, period=period, status="network_error", errors=[str(exc)])
        status = response_status(response.payload)
        if status:
            return self._failure(indicator, period, response, status, "利率来源状态: " + status)
        if not payload_shape_is_valid(response.payload):
            return self._failure(indicator, period, response, "parse_error", "利率来源响应结构无法解析")
        expected = self._families.get(indicator.indicator_id)
        points = []
        try:
            for row in payload_rows(response.payload):
                if normalize_period(row.get("period", row.get("date", row.get("time", period))), indicator.frequency) != period:
                    continue
                actual = str(row.get("family", row.get("series", row.get("instrument", "")))).strip().lower()
                if expected and actual and actual != expected.lower():
                    if actual not in self._proxies.get(indicator.indicator_id, set()):
                        raise ValueError(f"利率/汇率口径不匹配：需要 {expected}，收到 {actual}")
                    if not row.get("is_proxy"):
                        raise ValueError(f"收到 {actual} 代理序列，但未标记 is_proxy=true")
                tenor = str(row.get("tenor", row.get("maturity", ""))).lower()
                if "10年" in indicator.name and tenor and tenor not in {"10y", "10-year", "10年"}:
                    raise ValueError("国债收益率期限不是10年")
                if "dr007" in indicator.indicator_id and tenor and tenor not in {"007", "dr007", "7d"}:
                    raise ValueError("银行间利率期限不是DR007")
                points.append(make_point(source=self.source, indicator=indicator, row=row, period=period, response=response, value=row.get("value", row.get("data"))))
        except (NormalizationError, ValueError) as exc:
            return self._failure(indicator, period, response, "definition_mismatch", str(exc))
        if not points:
            return self._failure(indicator, period, response, "not_published", "利率/汇率来源尚未发布该统计期数据")
        return self._finish(indicator=indicator, period=period, response=response, points=points)
