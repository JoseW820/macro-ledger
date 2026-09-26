"""Shared transport and audit helpers for phase-three official providers."""

from __future__ import annotations

import hashlib
import json
import csv
import io
import os
import time
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.models import DataPoint, FetchResult, IndicatorDefinition
from app.pipeline.normalize import normalize_period, parse_numeric, save_normalized_points


@dataclass(frozen=True)
class OfficialResponse:
    payload: Any
    source_url: str
    release_date: str | None = None
    retrieved_at: str = ""
    raw_bytes: bytes | None = None
    status_code: int = 200
    headers: Mapping[str, str] | None = None

    def with_timestamp(self) -> "OfficialResponse":
        if self.retrieved_at:
            return self
        return OfficialResponse(
            payload=self.payload,
            source_url=self.source_url,
            release_date=self.release_date,
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            raw_bytes=self.raw_bytes,
            status_code=self.status_code,
            headers=self.headers,
        )


class OfficialFetcher(Protocol):
    def __call__(self, indicator: IndicatorDefinition, period: str) -> OfficialResponse | Any: ...


def json_http_fetcher(
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    timeout: float = 20.0,
    retries: int = 2,
    backoff_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> OfficialResponse:
    """Fetch a JSON endpoint while retaining bytes for hashing and audit."""

    params = params or {}
    request_url = f"{url}?{urlencode(params)}" if params and not url.startswith("file:") else url
    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            request = Request(
                request_url,
                headers={
                    "Accept": "application/json,text/plain,*/*",
                    "User-Agent": "macro-ledger/0.1 (+official-data-client)",
                },
            )
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                payload = json.loads(raw.decode("utf-8-sig"))
                return OfficialResponse(
                    payload=payload,
                    source_url=request_url,
                    retrieved_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    raw_bytes=raw,
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                )
        except Exception as exc:  # urllib has several platform-specific error classes
            last_error = exc
            if attempt < retries:
                sleep(backoff_seconds * (2**attempt))
    raise OSError(str(last_error or "官方接口请求失败"))


def file_or_json_fetcher(
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    backoff_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> OfficialResponse:
    """Fetch official JSON/CSV/text attachments without requiring pandas."""

    params = params or {}
    request_url = f"{url}?{urlencode(params)}" if params and not url.startswith("file:") else url
    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            request = Request(request_url, headers={"Accept": "application/json,text/csv,text/plain,*/*", "User-Agent": "macro-ledger/0.1"})
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                content_type = str(response.headers.get("Content-Type", "")).lower()
                try:
                    payload = json.loads(raw.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    text = raw.decode("utf-8-sig", errors="replace")
                    if "csv" in content_type or "," in text.splitlines()[0]:
                        payload = list(csv.DictReader(io.StringIO(text)))
                    else:
                        payload = {"text": text}
                return OfficialResponse(payload=payload, source_url=request_url, retrieved_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"), raw_bytes=raw, status_code=response.status, headers=dict(response.headers.items()))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                sleep(backoff_seconds * (2**attempt))
    raise OSError(str(last_error or "官方文件请求失败"))


def html_fetcher(url: str, *, timeout: float = 30.0, retries: int = 2, sleep: Callable[[float], None] = time.sleep) -> OfficialResponse:
    """Fetch an official HTML page while preserving the raw bytes."""
    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            request = Request(url, headers={"Accept": "text/html,*/*", "User-Agent": "macro-ledger/0.1 (+official-data-client)"})
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return OfficialResponse(payload=raw.decode("utf-8-sig", errors="replace"), source_url=url, retrieved_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"), raw_bytes=raw, status_code=response.status, headers=dict(response.headers.items()))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                sleep(0.5 * (2**attempt))
    raise OSError(str(last_error or "官方网页请求失败"))


def download_bytes(url: str, *, timeout: float = 60.0, retries: int = 2, sleep: Callable[[float], None] = time.sleep) -> OfficialResponse:
    """Download an official attachment without assuming its extension is stable."""
    last_error: Exception | None = None
    for attempt in range(max(0, retries) + 1):
        try:
            request = Request(url, headers={"Accept": "application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*", "User-Agent": "macro-ledger/0.1 (+official-data-client)"})
            with urlopen(request, timeout=timeout) as response:
                raw = response.read()
                return OfficialResponse(payload={"content_type": response.headers.get("Content-Type", ""), "bytes": len(raw)}, source_url=url, retrieved_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"), raw_bytes=raw, status_code=response.status, headers=dict(response.headers.items()))
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                sleep(0.5 * (2**attempt))
    raise OSError(str(last_error or "官方附件下载失败"))


def configured_endpoint_fetcher(env_name: str) -> Callable[[IndicatorDefinition, str], OfficialResponse]:
    """Build a fetcher from an environment-provided official endpoint."""

    def fetcher(indicator: IndicatorDefinition, period: str) -> OfficialResponse:
        endpoint = os.getenv(env_name)
        if not endpoint:
            raise LookupError(f"{env_name} 未设置")
        return file_or_json_fetcher(endpoint, params={"indicator_id": indicator.indicator_id, "period": period})

    return fetcher


def coerce_response(value: OfficialResponse | Any, *, default_source: str) -> OfficialResponse:
    if isinstance(value, OfficialResponse):
        return value.with_timestamp()
    raw = json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")
    return OfficialResponse(
        payload=value,
        source_url=default_source,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        raw_bytes=raw,
    )


def payload_rows(payload: Any) -> list[dict[str, Any]]:
    """Extract rows from common official JSON envelopes without guessing columns."""

    current = payload
    if isinstance(current, dict):
        for key in ("data", "rows", "records", "observations", "results", "items", "list"):
            if key in current:
                current = current[key]
                break
    if isinstance(current, dict):
        for key in ("data", "rows", "records", "observations", "results", "items", "list"):
            if key in current:
                current = current[key]
                break
    if isinstance(current, dict):
        current = [current]
    if not isinstance(current, list):
        return []
    return [row for row in current if isinstance(row, dict)]


def payload_shape_is_valid(payload: Any) -> bool:
    if isinstance(payload, list):
        return True
    if not isinstance(payload, dict):
        return False
    if any(key in payload for key in ("period", "date", "time", "value", "data")):
        return True
    for key in ("data", "rows", "records", "observations", "results", "items", "list"):
        if key in payload and isinstance(payload[key], (list, dict)):
            return True
    return False


def response_status(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    status = payload.get("status", payload.get("state"))
    if isinstance(status, str):
        normalized = status.lower()
        if normalized in {"not_published", "unpublished", "尚未发布", "未发布"}:
            return "not_published"
        if normalized in {"source_changed", "changed", "schema_changed"}:
            return "source_changed"
        if normalized in {"parse_error", "invalid"}:
            return "parse_error"
    if payload.get("published") is False:
        return "not_published"
    return None


def save_official_artifact(
    *,
    source: str,
    indicator: IndicatorDefinition,
    period: str,
    response: OfficialResponse,
    request: Mapping[str, Any] | None = None,
    root: Path,
) -> tuple[str, str]:
    """Save raw payload, request metadata and definition snapshot; return path/hash."""

    response = response.with_timestamp()
    raw_bytes = response.raw_bytes or json.dumps(response.payload, ensure_ascii=False, default=str).encode("utf-8")
    digest = hashlib.sha256(raw_bytes).hexdigest()
    stamp = response.retrieved_at.replace(":", "").replace("+00:00", "Z")
    directory = root / "raw" / source / indicator.indicator_id / period
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{stamp}.json"
    suffix = 1
    while target.exists():
        target = directory / f"{stamp}_{suffix}.json"
        suffix += 1
    envelope = {
        "source": source,
        "source_url": response.source_url,
        "release_date": response.release_date,
        "retrieved_at": response.retrieved_at,
        "sha256": digest,
        "request": dict(request or {}),
        "definition": asdict(indicator),
        "response": response.payload,
    }
    target.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(target), digest


def make_point(
    *,
    source: str,
    indicator: IndicatorDefinition,
    row: Mapping[str, Any],
    period: str,
    response: OfficialResponse,
    value: Any,
    calculation_method: str = "official_value",
) -> DataPoint:
    normalized_period = normalize_period(period, indicator.frequency)
    parsed = parse_numeric(value)
    if parsed is None:
        raise ValueError("官方数据值为空")
    return DataPoint(
        indicator_id=indicator.indicator_id,
        indicator_name=indicator.name,
        period=normalized_period,
        value=parsed,
        unit=str(row.get("unit", indicator.unit)),
        frequency=indicator.frequency,
        source=source,
        source_url=response.source_url,
        release_date=response.release_date,
        retrieved_at=response.retrieved_at,
        definition=indicator.definition,
        calculation_method=calculation_method,
        revision_status=str(row.get("revision_status", "original")),
        quality_status="unverified",
    )


class OfficialProviderBase:
    """Base class for transport/audit; subclasses own source-specific semantics."""

    source = "official"

    def __init__(self, *, fetcher: OfficialFetcher | None = None, data_root: Path | str = Path("data")) -> None:
        self.fetcher = fetcher
        self.data_root = Path(data_root)

    def _fetch_response(self, indicator: IndicatorDefinition, period: str) -> OfficialResponse:
        if self.fetcher is None:
            raise LookupError(f"{self.source} Provider 未配置官方 fetcher")
        return coerce_response(self.fetcher(indicator, period), default_source=self.source)

    def _finish(
        self,
        *,
        indicator: IndicatorDefinition,
        period: str,
        response: OfficialResponse,
        points: Iterable[DataPoint],
        request: Mapping[str, Any] | None = None,
    ) -> FetchResult:
        point_list = list(points)
        raw_artifact, digest = save_official_artifact(
            source=self.source,
            indicator=indicator,
            period=period,
            response=response,
            request=request,
            root=self.data_root,
        )
        if not point_list:
            return FetchResult(indicator=indicator, period=period, raw_artifact=raw_artifact, status="not_published", errors=["官方来源没有该统计期数据"], metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url})
        normalized = save_normalized_points(point_list, self.data_root / "normalized")
        return FetchResult(
            indicator=indicator,
            period=period,
            points=point_list,
            raw_artifact=raw_artifact,
            status="success",
            metadata={"sha256": digest, "release_date": response.release_date, "source_url": response.source_url, "normalized_artifact": str(normalized)},
        )
