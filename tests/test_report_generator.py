from pathlib import Path

from app.models import DataPoint
from app.report.generator import generate_excel, generate_html


def test_report_outputs_keep_missing_values_visible(tmp_path: Path):
    points = [DataPoint("cpi_yoy", "CPI同比", "2025-08", 0.7, "%", "monthly", "nbs", source_url="https://stats.test")]
    html_path = generate_html("2025-08", points, output_dir=tmp_path)
    excel_path = generate_excel("2025-08", points, output_dir=tmp_path)
    assert html_path.exists()
    assert "CPI同比" in html_path.read_text(encoding="utf-8")
    assert excel_path.exists()


def test_report_includes_confirmed_analysis(tmp_path: Path):
    point = DataPoint("cpi_yoy", "CPI", "2025-08", 0.2, "%", "monthly", "nbs")
    path = generate_html(
        "2025-08",
        [point],
        analysis={"overview": "需求仍弱", "themes": {"demand": {"status": "偏弱", "summary": "消费尚未修复"}}},
        output_dir=tmp_path,
    )
    content = path.read_text(encoding="utf-8")
    assert "需求仍弱" in content
    assert "消费尚未修复" in content


def test_report_includes_macro_regime_schema(tmp_path: Path):
    point = DataPoint("cpi_yoy", "CPI", "2026-08", 0.8, "%", "monthly", "nbs")
    path = generate_html(
        "2026-08",
        [point],
        analysis={
            "macro_regime": {"label": "供给有韧性", "confidence": "medium", "summary": "内需仍弱"},
            "themes": {"需求与收入": {"status": "偏弱", "supporting_evidence": ["零售同比 1.1%"]}},
            "contradictions": ["生产指标存在背离"],
            "unknowns": ["工业利润缺失"],
            "watchlist": ["观察下月消费"],
        },
        output_dir=tmp_path,
    )
    content = path.read_text(encoding="utf-8")
    assert "供给有韧性" in content
    assert "内需仍弱" in content
    assert "生产指标存在背离" in content
