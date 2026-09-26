"""PBOC workbook discovery and conservative monthly table parsing."""

from __future__ import annotations

import io
import math
import re
from datetime import date
from typing import Any

from .official import download_bytes
from .pboc import pboc_discover_topic_attachments


def _month(value: Any) -> str | None:
    text = f"{value:.2f}" if isinstance(value, float) else str(value or "").strip()
    match = re.fullmatch(r"(20\d{2})\.(\d{1,2})", text)
    if not match or not 1 <= int(match.group(2)) <= 12:
        return None
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}"


def parse_monthly_workbook(raw: bytes, *, value_column: int = 1, unit_marker: str = "亿元") -> list[dict[str, Any]]:
    """Parse only rows under the requested unit section; ignore notes and totals."""
    import openpyxl
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    rows: list[dict[str, Any]] = []
    for sheet in workbook.worksheets:
        active = False
        for record in sheet.iter_rows(values_only=True):
            values = list(record)
            first = "" if not values or values[0] is None else str(values[0])
            if "单位" in first:
                active = unit_marker in first
                continue
            if not active or len(values) <= value_column:
                continue
            period = _month(values[0])
            if not period:
                continue
            value = values[value_column]
            if value is None or isinstance(value, bool):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(numeric):
                rows.append({"period": period, "value": int(numeric) if numeric.is_integer() else numeric, "unit": unit_marker})
    return rows


def discover_and_download_pboc(topic: str, index_url: str, *, attachment_pattern: str = r"\.xlsx?", timeout: float = 60.0) -> list[tuple[str, bytes]]:
    urls = [url for url in pboc_discover_topic_attachments(index_url, topic) if re.search(attachment_pattern, url, re.I)]
    result: list[tuple[str, bytes]] = []
    for url in urls:
        response = download_bytes(url, timeout=timeout)
        result.append((url, response.raw_bytes or b""))
    return result
