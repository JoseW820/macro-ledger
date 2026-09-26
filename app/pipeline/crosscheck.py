"""Read-only cross-check against a user workbook; never overwrite official data."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from app.models import DataPoint


@dataclass
class CrossCheckReport:
    workbook: str
    sha256: str | None
    status: str
    matched: int = 0
    mismatched: int = 0
    missing: int = 0
    details: list[str] = field(default_factory=list)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def cross_check_workbook(points: Iterable[DataPoint], workbook: Path | str, *, tolerance: float = 1e-9) -> CrossCheckReport:
    """Compare identifiable rows in an XLSX file and report, without mutation."""

    path = Path(workbook)
    if not path.exists():
        return CrossCheckReport(str(path), None, "workbook_missing", missing=len(list(points)))
    digest = _sha256(path)
    try:
        import openpyxl  # type: ignore[import-not-found]
    except ImportError:
        return CrossCheckReport(str(path), digest, "dependency_missing", details=["安装 openpyxl 后才能读取 XLSX 交叉核对表"])
    rows = []
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet in book.worksheets:
        rows.extend(list(sheet.iter_rows(values_only=True)))
    report = CrossCheckReport(str(path), digest, "ok")
    for point in points:
        found = False
        for row in rows:
            cells = [str(cell).strip() for cell in row if cell is not None]
            joined = " | ".join(cells)
            if point.indicator_id not in joined and point.indicator_name not in joined:
                continue
            if point.period not in joined and point.period.replace("-", "") not in joined:
                continue
            numeric = []
            for cell in row:
                try:
                    numeric.append(float(cell))
                except (TypeError, ValueError):
                    continue
            if any(abs(value - float(point.value)) <= tolerance for value in numeric):
                report.matched += 1
            else:
                report.mismatched += 1
                report.details.append(f"{point.indicator_id} {point.period}: 对齐表数值不一致")
            found = True
            break
        if not found:
            report.missing += 1
    return report
