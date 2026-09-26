"""Ministry of Finance provider for budgets and government debt financing."""

from __future__ import annotations

from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import NormalizationError, normalize_period
from .official import OfficialProviderBase, OfficialResponse, make_point, payload_rows, payload_shape_is_valid, response_status, save_official_artifact


class MOFProvider(OfficialProviderBase):
    source = "mof"

    _budget_indicators = {
        "general_public_budget_revenue_ytd_yoy": "revenue",
        "general_public_budget_expenditure_ytd_yoy": "expenditure",
        "central_general_budget_revenue_ytd_yoy": "central_revenue",
        "local_general_budget_revenue_ytd_yoy": "local_revenue",
        "government_bond_net_financing_monthly": "government_bond_financing",
    }

    def _failure(self, indicator, period, response, status, message):
        artifact, digest = save_official_artifact(source=self.source, indicator=indicator, period=period, response=response, root=self.data_root)
        return FetchResult(indicator=indicator, period=period, raw_artifact=artifact, status=status, errors=[message], metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url})

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        if self.fetcher is None:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=["财政部官方 fetcher 未配置"])
        try:
            response = self._fetch_response(indicator, period)
        except LookupError as exc:
            return FetchResult(indicator=indicator, period=period, status="provider_unavailable", errors=[str(exc)])
        except OSError as exc:
            return FetchResult(indicator=indicator, period=period, status="network_error", errors=[str(exc)])
        status = response_status(response.payload)
        if status:
            return self._failure(indicator, period, response, status, "财政部来源状态: " + status)
        if not payload_shape_is_valid(response.payload):
            return self._failure(indicator, period, response, "parse_error", "财政部响应结构无法解析")
        expected = self._budget_indicators.get(indicator.indicator_id)
        points = []
        try:
            for row in payload_rows(response.payload):
                raw_period = row.get("period", row.get("date", row.get("time", period)))
                if normalize_period(raw_period, indicator.frequency) != period:
                    continue
                budget_type = str(row.get("budget_type", row.get("budget", "general_public_budget"))).strip().lower()
                if indicator.indicator_id.startswith(("general_public_budget", "central_general_budget", "local_general_budget")) and budget_type not in {"general_public_budget", "一般公共预算", "general"}:
                    raise ValueError("财政数据不是一般公共预算口径")
                series = str(row.get("series", row.get("measure", ""))).strip().lower()
                if indicator.value_type == "ytd_yoy" and series and not any(word in series for word in ("ytd", "累计", "同比", "year_to_date")):
                    raise ValueError("财政累计同比指标收到非累计口径")
                if expected and row.get("series_id") and str(row["series_id"]).lower() != expected.lower():
                    raise ValueError(f"财政指标口径不匹配：需要 {expected}")
                points.append(make_point(source=self.source, indicator=indicator, row=row, period=period, response=response, value=row.get("value", row.get("data"))))
        except (NormalizationError, ValueError) as exc:
            return self._failure(indicator, period, response, "definition_mismatch", str(exc))
        if not points:
            return self._failure(indicator, period, response, "not_published", "财政部尚未发布该统计期数据")
        return self._finish(indicator=indicator, period=period, response=response, points=points)
