import json
from pathlib import Path

from app.agent_context import generate_agent_context
from app.models import DataPoint, IndicatorDefinition


def test_agent_context_contains_facts_quality_and_prompt(tmp_path: Path):
    indicator = IndicatorDefinition(
        indicator_id="cpi_yoy", name="CPI同比", theme="prices", frequency="monthly", unit="%", value_type="monthly_yoy", primary_source="nbs", definition="居民消费价格同比",
    )
    point = DataPoint("cpi_yoy", "CPI同比", "2026-08", 0.7, "%", "monthly", "nbs", source_url="https://stats.example")
    target = generate_agent_context("2026-08", [point], [indicator], output_dir=tmp_path)
    facts = json.loads((target / "facts.json").read_text(encoding="utf-8"))
    assert facts["observations"][0]["indicator_id"] == "cpi_yoy"
    prompt = (target / "analysis-prompt.md").read_text(encoding="utf-8")
    assert "facts.json" in prompt
    assert "cross_theme_links" in prompt
    assert "logic_chain" in prompt
    assert "future_implications" in prompt
    assert (target / "quality-report.md").exists()
    assert (target.with_suffix(".zip")).exists()
