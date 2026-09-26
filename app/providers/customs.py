"""General Administration of Customs provider for national trade data."""

from __future__ import annotations

from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period
from .official import OfficialProviderBase, OfficialResponse, make_point, payload_rows, payload_shape_is_valid, response_status, save_official_artifact


class CustomsProvider(OfficialProviderBase):
    source = "customs"

    def _failure(self, indicator, period, response, status, message):
        artifact, digest = save_official_artifact(source=self.source, indicator=indicator, period=period, response=response, root=self.data_root)
        return FetchResult(indicator=indicator, period=period, raw_artifact=artifact, status=status, errors=[message], metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url})

    @staticmethod
    def _is_national(row):
        scope = str(row.get("scope", row.get("trade_scope", row.get("region", "全国")))).strip().lower()
        partner = str(row.get("partner", row.get("partner_country", "全国"))).strip().lower()
        return scope in {"全国", "中国", "china", "national", ""} and partner in {"全国", "中国", "china", "national", "all", ""}

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        if self.fetcher is None:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=["海关总署官方 fetcher 未配置"])
        try:
            response = self._fetch_response(indicator, period)
        except LookupError as exc:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[str(exc)])
        except OSError as exc:
            return FetchResult(indicator=indicator, period=period, status="network_error", errors=[str(exc)])
        status = response_status(response.payload)
        if status:
            return self._failure(indicator, period, response, status, "海关来源状态: " + status)
        if not payload_shape_is_valid(response.payload):
            return self._failure(indicator, period, response, "parse_error", "海关响应结构无法解析")
        points = []
        try:
            for row in payload_rows(response.payload):
                raw_period = row.get("period", row.get("date", row.get("time", period)))
                if normalize_period(raw_period, indicator.frequency) != period:
                    continue
                if not self._is_national(row):
                    raise ValueError("海关数据不是全国贸易口径，或包含双边贸易")
                currency = str(row.get("currency", row.get("currency_name", ""))).lower()
                if "人民币" in indicator.unit and currency and currency not in {"人民币", "cny", "rmb", "yuan"}:
                    raise ValueError("海关数据不是人民币口径")
                measure = str(row.get("measure", row.get("value_type", "amount"))).lower()
                if "quantity" in measure or "数量" in measure:
                    raise ValueError("海关数量数据不能用于金额指标")
                if not indicator.allow_cumulative and any(word in measure for word in ("cumulative", "累计", "ytd")):
                    raise ValueError("海关累计值不能用于当月指标")
                value = row.get("value", row.get("data"))
                method = "official_value"
                if indicator.indicator_id == "trade_balance_rmb_monthly" and value in (None, ""):
                    exports = row.get("exports", row.get("export_value"))
                    imports = row.get("imports", row.get("import_value"))
                    if exports is None or imports is None:
                        continue
                    value = float(exports) - float(imports)
                    method = "exports_minus_imports"
                points.append(make_point(source=self.source, indicator=indicator, row=row, period=period, response=response, value=value, calculation_method=method))
        except (NormalizationError, ValueError, TypeError) as exc:
            return self._failure(indicator, period, response, "definition_mismatch", str(exc))
        if not points:
            return self._failure(indicator, period, response, "not_published", "海关尚未发布该统计期全国贸易数据")
        return self._finish(indicator=indicator, period=period, response=response, points=points)
