"""State Administration of Foreign Exchange provider.

The provider keeps three concepts separate: bank settlement, bank-client
cross-border receipts/payments, and the balance of payments.
"""

from __future__ import annotations

from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period
from .official import OfficialProviderBase, OfficialResponse, make_point, payload_rows, payload_shape_is_valid, response_status, save_official_artifact, html_fetcher
from .discovery import DiscoveredLink, discover_links
import re
from html import unescape


def discover_safe_monthly_articles(index_html: str, base_url: str = "https://www.safe.gov.cn") -> list[DiscoveredLink]:
    """Find SAFE articles for settlement and cross-border receipts/payments."""
    return discover_links(index_html, base_url, text_pattern=r"结售汇|涉外收付款")


def fetch_safe_article(url: str) -> OfficialResponse:
    """Fetch a SAFE article for a source-specific parser."""
    return html_fetcher(url)


def parse_safe_article(html: str, period: str) -> list[dict[str, object]]:
    """Extract the four headline amounts from SAFE's monthly article prose."""
    text = unescape(re.sub(r"<[^>]+>", " ", html))
    text = " ".join(text.split())
    if not re.search(re.escape(period[:4]) + r"年" + str(int(period[5:])) + r"月", text):
        return []
    patterns = {
        "bank_settlement": r"银行结汇\s*([\d,.]+)\s*亿元人民币，售汇\s*([\d,.]+)\s*亿元人民币",
        "cross_border_receipts_payments": r"银行代客涉外收入\s*([\d,.]+)\s*亿元人民币，对外付款\s*([\d,.]+)\s*亿元人民币",
    }
    rows: list[dict[str, object]] = []
    for series, pattern in patterns.items():
        match = re.search(pattern, text)
        if not match:
            continue
        settlement = float(match.group(1).replace(",", ""))
        payment = float(match.group(2).replace(",", ""))
        rows.append({"period": period, "series": series, "value": settlement - payment, "unit": "亿元人民币", "measure": "monthly_balance", "currency": "人民币", "components": {"inflow": settlement, "outflow": payment}})
    return rows


class SAFEProvider(OfficialProviderBase):
    source = "safe"

    _series = {
        "bank_settlement_balance_usd": "bank_settlement",
        "bank_cross_border_receipts_payments_balance_usd": "cross_border_receipts_payments",
        "international_balance_current_account": "balance_of_payments",
        "foreign_exchange_reserves_usd": "foreign_exchange_reserves",
    }

    def _failure(self, indicator, period, response, status, message):
        artifact, digest = save_official_artifact(source=self.source, indicator=indicator, period=period, response=response, root=self.data_root)
        return FetchResult(indicator=indicator, period=period, raw_artifact=artifact, status=status, errors=[message], metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url})

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        if self.fetcher is None:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=["国家外汇管理局官方 fetcher 未配置"])
        try:
            response = self._fetch_response(indicator, period)
        except LookupError as exc:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[str(exc)])
        except OSError as exc:
            return FetchResult(indicator=indicator, period=period, status="network_error", errors=[str(exc)])
        status = response_status(response.payload)
        if status:
            return self._failure(indicator, period, response, status, "外汇局来源状态: " + status)
        if not payload_shape_is_valid(response.payload):
            return self._failure(indicator, period, response, "parse_error", "外汇局响应结构无法解析")
        expected = self._series.get(indicator.indicator_id)
        points = []
        try:
            for row in payload_rows(response.payload):
                raw_period = row.get("period", row.get("date", row.get("time", period)))
                if normalize_period(raw_period, indicator.frequency) != period:
                    continue
                actual = str(row.get("series", row.get("table", row.get("series_type", "")))).strip().lower()
                if expected and actual and actual not in {expected.lower(), indicator.name.lower()}:
                    raise ValueError(f"外汇局口径不匹配：需要 {expected}，收到 {actual}")
                currency = str(row.get("currency", row.get("currency_name", "美元"))).strip().lower()
                if "美元" in indicator.unit and currency not in {"美元", "usd", "us dollar", "dollar"}:
                    raise ValueError("外汇局数据不是美元口径")
                points.append(make_point(source=self.source, indicator=indicator, row=row, period=period, response=response, value=row.get("value", row.get("data"))))
        except (NormalizationError, ValueError) as exc:
            return self._failure(indicator, period, response, "definition_mismatch", str(exc))
        if not points:
            return self._failure(indicator, period, response, "not_published", "外汇局尚未发布该统计期数据")
        return self._finish(indicator=indicator, period=period, response=response, points=points)
