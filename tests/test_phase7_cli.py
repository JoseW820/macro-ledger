from pathlib import Path

from app.cli import build_parser
from app.web import _xlsx_rows


def test_phase7_commands_are_registered():
    parser = build_parser()
    for command in ("doctor", "status", "web", "report"):
        args = parser.parse_args([command] + (["--period", "2026-08"] if command in {"status", "report"} else []))
        assert args.command == command


def test_repository_security_files_use_placeholders():
    root = Path(__file__).parents[1]
    env = (root / ".env.example").read_text(encoding="utf-8")
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "your_fred_api_key_here" in env
    assert ".env" in ignore
    assert "*.key" in ignore
    assert "data/*.sqlite" in ignore


def test_web_xlsx_rows_ignore_footnotes_and_normalize_months(tmp_path: Path):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["说明", None])
    sheet.append(["月份", "指标值"])
    sheet.append(["2026年7月", 4.5])
    sheet.append(["数据来源", "https://stats.gov.cn"])
    path = tmp_path / "official.xlsx"
    workbook.save(path)
    assert _xlsx_rows(path) == [{"period": "2026-07", "value": 4.5, "unit": "%"}]
