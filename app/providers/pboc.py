"""People's Bank of China provider for money, credit and rates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period
from .official import OfficialProviderBase, OfficialResponse, make_point, payload_rows, payload_shape_is_valid, response_status, save_official_artifact, download_bytes, html_fetcher
from .discovery import discover_links


def discover_pboc_workbook_urls(index_html: str, base_url: str = "https://www.pbc.gov.cn") -> dict[int, str]:
    """Discover yearly PBOC statistics pages without hard-coding numeric IDs."""
    result: dict[int, str] = {}
    import re
    for link in discover_links(index_html, base_url, text_pattern=r"\d{4}年统计数据"):
        match = re.search(r"(20\d{2})年统计数据", link.text)
        if match:
            result[int(match.group(1))] = link.url
    return result


def discover_pboc_attachment(topic_html: str, base_url: str, table_label: str) -> str | None:
    """Find an xls/xlsx link near a named PBOC table."""
    marker = topic_html.find(table_label)
    if marker < 0:
        return None
    links = discover_links(topic_html[marker : marker + 1800], base_url, href_pattern=r"\.xlsx?($|\?)")
    return links[0].url if links else None


def discover_pboc_topic(index_html: str, base_url: str, topic: str) -> str | None:
    links = discover_links(index_html, base_url, text_pattern=rf"{topic}")
    return links[0].url if links else None


def pboc_discover_attachment(index_url: str, topic: str, table_label: str) -> str | None:
    """Walk the live PBOC index -> yearly page -> topic page -> workbook."""
    index = html_fetcher(index_url)
    sections = discover_pboc_workbook_urls(str(index.payload), index_url)
    if not sections:
        return None
    year_url = sections[max(sections)]
    section = html_fetcher(year_url)
    topic_url = discover_pboc_topic(str(section.payload), year_url, topic)
    if not topic_url:
        return None
    topic_page = html_fetcher(topic_url)
    return discover_pboc_attachment(str(topic_page.payload), topic_url, table_label)


def pboc_discover_topic_attachments(index_url: str, topic: str) -> list[str]:
    """Return all workbook links from the latest yearly topic page."""
    index = html_fetcher(index_url)
    sections = discover_pboc_workbook_urls(str(index.payload), index_url)
    if not sections:
        return []
    year_url = sections[max(sections)]
    section = html_fetcher(year_url)
    topic_url = discover_pboc_topic(str(section.payload), year_url, topic)
    if not topic_url:
        return []
    topic_page = html_fetcher(topic_url)
    return [link.url for link in discover_links(str(topic_page.payload), topic_url, href_pattern=r"\.xlsx?($|\?)")]


class PBOCProvider(OfficialProviderBase):
    source = "pboc"

    _expected_series = {
        "m0_yoy": {"m0", "货币供应量m0", "流通中货币"},
        "m1_yoy": {"m1", "货币供应量m1"},
        "m2_yoy": {"m2", "货币供应量m2"},
        "social_financing_stock_yoy": {"social_financing_stock", "社会融资规模存量"},
        "social_financing_increment_monthly": {"social_financing_increment", "社会融资规模增量"},
        "rmb_loans_stock_yoy": {"rmb_loans_stock", "人民币贷款余额"},
        "rmb_loans_increment_monthly": {"rmb_loans_increment", "人民币贷款增量"},
        "rmb_deposits_stock_yoy": {"rmb_deposits_stock", "人民币存款余额"},
        "loan_prime_rate_1y": {"lpr_1y", "贷款市场报价利率1年期", "1年期lpr"},
    }

    def _failure(self, indicator: IndicatorDefinition, period: str, response: OfficialResponse, status: str, message: str) -> FetchResult:
        artifact, digest = save_official_artifact(
            source=self.source,
            indicator=indicator,
            period=period,
            response=response,
            root=self.data_root,
        )
        return FetchResult(
            indicator=indicator,
            period=period,
            raw_artifact=artifact,
            status=status,
            errors=[message],
            metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url},
        )

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        if self.fetcher is None:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=["人民银行官方 fetcher 未配置"])
        try:
            response = self._fetch_response(indicator, period)
        except LookupError as exc:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[str(exc)])
        except OSError as exc:
            return FetchResult(indicator=indicator, period=period, status="network_error", errors=[str(exc)])
        status = response_status(response.payload)
        if status:
            return self._failure(indicator, period, response, status, "人民银行来源状态: " + status)
        if not payload_shape_is_valid(response.payload):
            return self._failure(indicator, period, response, "parse_error", "人民银行响应结构无法解析")
        rows = payload_rows(response.payload)
        points = []
        try:
            expected = self._expected_series.get(indicator.indicator_id)
            for row in rows:
                raw_period = row.get("period", row.get("date", row.get("time", period)))
                if normalize_period(raw_period, indicator.frequency) != period:
                    continue
                if expected:
                    series = str(row.get("series", row.get("metric", row.get("indicator_id", "")))).strip().lower()
                    if series and series not in {item.lower() for item in expected}:
                        raise ValueError(f"人民银行指标口径不匹配: {series}")
                currency = str(row.get("currency", row.get("currency_name", "人民币"))).strip().lower()
                if "人民币" in indicator.name or "rmb" in indicator.indicator_id:
                    if currency not in {"人民币", "cny", "rmb", "yuan"}:
                        raise ValueError("人民银行数据不是人民币口径")
                measure = str(row.get("measure", row.get("value_type", ""))).lower()
                if indicator.value_type == "stock_yoy" and any(word in measure for word in ("increment", "flow", "增量")):
                    raise ValueError("人民银行增量数据不能用于存量同比指标")
                if indicator.value_type == "monthly_absolute" and any(word in measure for word in ("stock", "balance", "存量", "余额")):
                    raise ValueError("人民银行存量数据不能用于当月增量指标")
                points.append(make_point(source=self.source, indicator=indicator, row=row, period=period, response=response, value=row.get("value", row.get("data"))))
        except (NormalizationError, ValueError) as exc:
            return self._failure(indicator, period, response, "definition_mismatch", str(exc))
        if not points:
            return self._failure(indicator, period, response, "not_published", "人民银行尚未发布该统计期数据")
        return self._finish(indicator=indicator, period=period, response=response, points=points)
