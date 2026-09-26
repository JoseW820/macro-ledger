"""Independent HTTP provider for the National Bureau of Statistics database."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import FetchResult, IndicatorDefinition
from app.pipeline.normalize import (
    NormalizationError,
    normalize_nbs_payload,
    period_to_api_code,
    save_normalized_points,
    save_normalized_series,
)


class NBSProviderError(RuntimeError):
    """Base error for NBS transport and response problems."""


class IndicatorNotFoundError(NBSProviderError):
    """The configured or searched indicator does not exist."""


class NoDataError(NBSProviderError):
    """The indicator exists but has no observation for the requested period."""


class DefinitionMismatchError(NBSProviderError):
    """The response is not the configured national/frequency/value definition."""


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: bytes
    headers: Mapping[str, str]


HttpGet = Callable[[str, Mapping[str, str], float], HttpResponse]


def _default_http_get(url: str, params: Mapping[str, str], timeout: float) -> HttpResponse:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(
        request_url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://data.stats.gov.cn/",
            "User-Agent": "macro-ledger/0.1 (+official-data-client)",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return HttpResponse(response.status, response.read(), dict(response.headers.items()))
    except HTTPError as exc:
        body = exc.read() if exc.fp else b""
        return HttpResponse(exc.code, body, dict(exc.headers.items()) if exc.headers else {})


def _safe_json(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NBSProviderError(f"统计局响应不是合法 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise NBSProviderError("统计局响应根节点不是对象")
    return value


class NBSProvider:
    """Fetch confirmed NBS series and preserve every request/response artifact.

    ``code_map`` must contain codes that have been manually confirmed against
    the NBS catalog. Search results are exposed by :meth:`search` but are never
    silently promoted to a production series.
    """

    def __init__(
        self,
        *,
        base_url: str = "https://data.stats.gov.cn/easyquery.htm",
        code_map: Mapping[str, str] | None = None,
        data_root: Path | str = Path("data"),
        timeout: float = 20.0,
        retries: int = 2,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        http_get: HttpGet | None = None,
    ) -> None:
        self.base_url = base_url
        self.code_map = dict(code_map or {})
        self.data_root = Path(data_root)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.sleep = sleep
        self.http_get = http_get or _default_http_get

    def _request(self, params: Mapping[str, str]) -> tuple[dict[str, Any], str]:
        last_error: Exception | None = None
        request_url = f"{self.base_url}?{urlencode(params)}"
        for attempt in range(self.retries + 1):
            try:
                response = self.http_get(self.base_url, params, self.timeout)
                if response.status_code != 200:
                    raise NBSProviderError(f"统计局 HTTP {response.status_code}")
                payload = _safe_json(response.body)
                return payload, request_url
            except (URLError, TimeoutError, OSError, NBSProviderError) as exc:
                last_error = exc
                if attempt < self.retries:
                    self.sleep(self.backoff_seconds * (2**attempt))
        raise NBSProviderError(str(last_error or "统计局请求失败"))

    def search(self, query: str, *, dbcode: str = "hgyd") -> list[dict[str, Any]]:
        """Search catalog candidates for human confirmation."""

        payload, _ = self._request(
            {"m": "SearchData", "dbcode": dbcode, "searchword": query, "h": "1"}
        )
        result = payload.get("returndata", payload)
        if isinstance(result, dict):
            for key in ("datanodes", "nodes", "results", "list"):
                if isinstance(result.get(key), list):
                    return [item for item in result[key] if isinstance(item, dict)]
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
        return []

    def _save_raw(
        self,
        indicator: IndicatorDefinition,
        period: str,
        payload: dict[str, Any] | None,
        params: Mapping[str, str],
        request_url: str,
        retrieved_at: str,
    ) -> str:
        stamp = retrieved_at.replace("+00:00", "Z").replace(":", "").replace("-", "")
        directory = self.data_root / "raw" / "nbs" / indicator.indicator_id / period / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "request.json").write_text(
            json.dumps({"url": request_url, "params": dict(params), "retrieved_at": retrieved_at}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (directory / "definition.json").write_text(
            json.dumps(asdict(indicator), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if payload is not None:
            (directory / "response.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return str(directory)

    def fetch(self, indicator: IndicatorDefinition, period: str) -> FetchResult:
        """Fetch one confirmed series for one canonical period."""

        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        code = self.code_map.get(indicator.indicator_id)
        if not code:
            return FetchResult(
                indicator=indicator,
                period=period,
                status="indicator_not_found",
                errors=["未配置经人工确认的国家统计局指标代码；请先 search 后确认"],
                metadata={"candidates": [], "retrieved_at": retrieved_at},
            )
        try:
            api_period = period_to_api_code(period, indicator.frequency)
            params = {
                "m": "QueryData",
                "dbcode": "hgyd",
                "rowcode": "zb",
                "colcode": "sj",
                "wds": "[]",
                "dfwds": json.dumps([{"wdcode": "zb", "valuecode": code}], ensure_ascii=False, separators=(",", ":")),
                "k1": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
                "h": "1",
            }
            payload, request_url = self._request(params)
            raw_artifact = self._save_raw(indicator, period, payload, params, request_url, retrieved_at)
            returncode = payload.get("returncode")
            if returncode not in (None, 0, "0"):
                return FetchResult(
                    indicator=indicator,
                    period=period,
                    raw_artifact=raw_artifact,
                    status="indicator_not_found" if str(returncode) in {"404", "100"} else "interface_error",
                    errors=[str(payload.get("returnmsg", f"统计局 returncode={returncode}"))],
                    metadata={"request_url": request_url, "retrieved_at": retrieved_at},
                )
            try:
                points = normalize_nbs_payload(payload, indicator, period, request_url, retrieved_at)
            except LookupError as exc:
                return FetchResult(indicator=indicator, period=period, raw_artifact=raw_artifact, status="no_data", errors=[str(exc)])
            except NormalizationError as exc:
                return FetchResult(
                    indicator=indicator,
                    period=period,
                    raw_artifact=raw_artifact,
                    status="definition_mismatch",
                    errors=[str(exc)],
                )
            normalized_path = save_normalized_points(points, self.data_root / "normalized")
            return FetchResult(
                indicator=indicator,
                period=period,
                points=points,
                raw_artifact=raw_artifact,
                status="success",
                metadata={
                    "request_url": request_url,
                    "api_period": api_period,
                    "retrieved_at": retrieved_at,
                    "normalized_artifact": str(normalized_path),
                },
            )
        except NBSProviderError as exc:
            raw_artifact = self._save_raw(indicator, period, None, locals().get("params", {}), self.base_url, retrieved_at)
            return FetchResult(
                indicator=indicator,
                period=period,
                raw_artifact=raw_artifact,
                status="transport_error" if "HTTP" not in str(exc) else "interface_error",
                errors=[str(exc)],
                metadata={"retrieved_at": retrieved_at},
            )
        except (ValueError, NormalizationError) as exc:
            return FetchResult(indicator=indicator, period=period, status="definition_mismatch", errors=[str(exc)])

    def fetch_history(
        self,
        indicator: IndicatorDefinition,
        *,
        start_period: str | None = None,
        end_period: str | None = None,
    ) -> FetchResult:
        """Fetch and persist the complete returned history for one series."""

        retrieved_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        code = self.code_map.get(indicator.indicator_id)
        history_label = f"{start_period or 'begin'}_{end_period or 'end'}"
        if not code:
            return FetchResult(
                indicator=indicator,
                period=history_label,
                status="indicator_not_found",
                errors=["未配置经人工确认的国家统计局指标代码；请先 search 后确认"],
            )
        params = {
            "m": "QueryData",
            "dbcode": "hgyd",
            "rowcode": "zb",
            "colcode": "sj",
            "wds": "[]",
            "dfwds": json.dumps([{"wdcode": "zb", "valuecode": code}], ensure_ascii=False, separators=(",", ":")),
            "k1": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
            "h": "1",
        }
        try:
            payload, request_url = self._request(params)
            raw_artifact = self._save_raw(indicator, history_label, payload, params, request_url, retrieved_at)
            if payload.get("returncode") not in (None, 0, "0"):
                return FetchResult(indicator=indicator, period=history_label, raw_artifact=raw_artifact, status="interface_error", errors=[str(payload.get("returnmsg", "统计局返回错误"))])
            points = normalize_nbs_payload(payload, indicator, None, request_url, retrieved_at)
            if start_period:
                points = [point for point in points if point.period >= start_period]
            if end_period:
                points = [point for point in points if point.period <= end_period]
            if not points:
                return FetchResult(indicator=indicator, period=history_label, raw_artifact=raw_artifact, status="no_data", errors=["统计局历史序列为空"])
            normalized_path = save_normalized_series(points, self.data_root / "normalized")
            return FetchResult(
                indicator=indicator,
                period=history_label,
                points=points,
                raw_artifact=raw_artifact,
                status="success",
                metadata={"request_url": request_url, "normalized_artifact": str(normalized_path), "retrieved_at": retrieved_at},
            )
        except NBSProviderError as exc:
            raw_artifact = self._save_raw(indicator, history_label, None, params, self.base_url, retrieved_at)
            return FetchResult(indicator=indicator, period=history_label, raw_artifact=raw_artifact, status="transport_error", errors=[str(exc)])
        except (ValueError, NormalizationError) as exc:
            return FetchResult(indicator=indicator, period=history_label, status="definition_mismatch", errors=[str(exc)])
