"""Build a bounded, source-grounded context package for an external AI agent."""

from __future__ import annotations

import json
import hashlib
import os
import zipfile
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from .analysis.quality import check_points
from .config import validate_config
from .models import DataPoint, IndicatorDefinition
from .pipeline.normalized import load_period_points as load_normalized_period_points


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_EXPORT_DIR = Path(os.environ.get("MACRO_AGENT_EXPORT_DIR", str(PROJECT_ROOT / "data" / "agent_context"))).expanduser()


def load_period_points(data_root: Path | str, period: str) -> list[DataPoint]:
    return load_normalized_period_points(data_root, period)


def _fact_rows(points: list[DataPoint]) -> list[dict[str, object]]:
    return [
        {
            "indicator_id": point.indicator_id,
            "indicator_name": point.indicator_name,
            "period": point.period,
            "value": point.value,
            "unit": point.unit,
            "frequency": point.frequency,
            "source": point.source,
            "source_url": point.source_url,
            "release_date": point.release_date,
            "retrieved_at": point.retrieved_at,
            "definition": point.definition,
            "calculation_method": point.calculation_method,
            "revision_status": point.revision_status,
            "quality_status": point.quality_status,
        }
        for point in points
    ]


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _history_points(data_root: Path | str, period: str, *, limit: int = 12) -> list[DataPoint]:
    root = Path(data_root) / "normalized"
    monthly = sorted({path.parent.name for path in root.glob("*/*/*.json") if len(path.parent.name) == 7 and path.parent.name[4] == "-" and path.parent.name != period}, reverse=True)
    selected = monthly[:limit]
    points: list[DataPoint] = []
    seen: set[tuple[str, str]] = set()
    for item in selected:
        for point in load_normalized_period_points(root.parent, item):
            key = (point.indicator_id, point.period)
            if key not in seen:
                points.append(point)
                seen.add(key)
    return points


def generate_agent_context(
    period: str,
    points: list[DataPoint],
    indicators: list[IndicatorDefinition],
    *,
    output_dir: Path | str = Path("data/agent_context"),
    history_points: list[DataPoint] | None = None,
) -> Path:
    """Overwrite the existing package with facts, history, quality and a constrained prompt."""
    target = Path(output_dir) / period
    target.mkdir(parents=True, exist_ok=True)
    definitions = {item.indicator_id: item for item in indicators}
    history_points = history_points or []
    # Keep the package internally consistent even when it is regenerated from
    # legacy normalized files written before the current unit contract.
    def contract_point(point: DataPoint) -> DataPoint:
        definition = definitions.get(point.indicator_id)
        return replace(point, unit=definition.unit, indicator_name=definition.name, frequency=definition.frequency, definition=definition.definition) if definition else point

    points = [contract_point(point) for point in points]
    current_keys = {(point.indicator_id, point.period) for point in points}
    history_points = [contract_point(point) for point in history_points if (point.indicator_id, point.period) not in current_keys]
    quality = check_points([*points, *history_points], indicators=indicators)
    observed = {point.indicator_id for point in points}
    missing = [item.indicator_id for item in indicators if item.indicator_id not in observed]
    latest_history: dict[str, DataPoint] = {}
    for point in sorted(history_points, key=lambda item: item.period, reverse=True):
        latest_history.setdefault(point.indicator_id, point)
    data_status = []
    for item in indicators:
        current = next((point for point in points if point.indicator_id == item.indicator_id), None)
        latest = current or latest_history.get(item.indicator_id)
        data_status.append({
            "indicator_id": item.indicator_id,
            "name": item.name,
            "frequency": item.frequency,
            "current_period": period if current and current.period == period else None,
            "current_value": current.value if current and current.period == period else None,
            "latest_available_period": latest.period if latest else None,
            "latest_available_value": latest.value if latest else None,
            "status": "current" if current and current.period == period else ("latest_available" if latest else "missing"),
        })
    facts = {
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "observations": _fact_rows(points),
        "history": _fact_rows(history_points),
        "data_status": data_status,
        "missing_indicator_ids": missing,
        "quality_issues": [asdict(issue) for issue in quality.issues],
        "rules": [
            "只使用 observations 和 history 中的事实，不补充外部数据。",
            "status 为 missing 或质量级别为 error 的指标不得用于方向性判断。",
            "latest_available 不等于 current；季度数据不得改写为月度数据。",
            "每条重要判断引用 indicator_id、统计期、数值、单位和 source。",
        ],
    }
    (target / "facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    evidence_lines = [f"# {period} 事实证据", "", "## 当前期与最近可用期", "", "| 指标 | 数值 | 统计期 | 单位 | 频率 | 来源 |", "|---|---:|---|---|---|---|"]
    for point in points:
        value = "当前无法判断" if point.value is None else str(point.value)
        evidence_lines.append(f"| {point.indicator_name} (`{point.indicator_id}`) | {value} | {point.period} | {point.unit} | {point.frequency} | {point.source} |")
    if history_points:
        evidence_lines.extend(["", "## 历史序列", "", f"已提供最近 {len({point.period for point in history_points})} 个历史统计期，完整数据见 `facts.json` 的 `history`。"])
    if missing:
        evidence_lines.extend(["", "## 当前期缺失指标", "", ", ".join(f"`{item}`" for item in missing)])
    _write(target / "evidence.md", "\n".join(evidence_lines) + "\n")
    issue_lines = [f"# {period} 数据质量报告", ""]
    if quality.issues:
        issue_lines.extend(["| 级别 | 代码 | 指标 | 统计期 | 说明 |", "|---|---|---|---|---|"])
        issue_lines.extend(f"| {issue.severity} | `{issue.code}` | {issue.indicator_id or '-'} | {issue.period or '-'} | {issue.message} |" for issue in quality.issues)
    else:
        issue_lines.append("未发现已配置检查项问题。")
    issue_lines.extend(["", "## 解释", "", "质量报告只对事实进行检查；存在 error 的指标不得用于方向性结论，warning 需要在分析中说明。"])
    _write(target / "quality-report.md", "\n".join(issue_lines) + "\n")
    definition_lines = [f"# {period} 指标定义", ""]
    for item in indicators:
        definition_lines.append(f"## {item.name} (`{item.indicator_id}`)\n- 主题：{item.theme}\n- 频率：{item.frequency}\n- 单位：{item.unit}\n- 值类型：{item.value_type}\n- 定义：{item.definition}\n- 主来源：{item.primary_source}\n")
    _write(target / "indicator-definitions.md", "\n".join(definition_lines))
    prompt = f"""# 宏观数据月度分析任务\n\n你是宏观数据分析助手。只读取同目录下的 `facts.json`、`evidence.md`、`quality-report.md` 和 `indicator-definitions.md`，分析统计期 **{period}**。\n\n## 硬性规则\n1. 只使用文件内数据，禁止联网、补数、猜测和股票买卖建议。\n2. 先检查 `data_status` 和 `quality_issues`；标记为 `missing` 或 `error` 的指标只能列入“无法判断”，不能作为支持证据。\n3. `latest_available` 不等于当期数据；月度、季度、累计值、存量值和当月值必须分开解释。\n4. 每个重要判断引用 `data_refs` 中的 indicator_id，并写明统计期、数值、单位和 source。\n5. 可以跨主题引用包内其他领域数据，但必须说明关系，不把相关性写成确定因果。\n6. 未来变化和影响必须使用条件表述（例如“如果……，则可能……”）；证据不足时输出“当前无法判断”。\n\n## 输出要求\n请同时输出一个严格 JSON 文件 `analysis-result.json`，不要把 Markdown 放进 JSON 字段。JSON 必须包含：\n```json\n{{\n  "period": "{period}",\n  "macro_regime": {{"label": "", "confidence": "high|medium|low", "summary": ""}},\n  "themes": {{\n    "生产与供给": {{\n      "status": "", "confidence": "high|medium|low",\n      "data_facts": [], "what_data_indicates": "",\n      "cross_theme_links": [{{"theme": "", "data_refs": [], "relationship": ""}}],\n      "logic_chain": [], "future_implications": [],\n      "supporting_evidence": [], "counter_evidence": [],\n      "unknowns": [], "watchlist": [], "data_refs": []\n    }}\n  }},\n  "evidence": [], "contradictions": [], "unknowns": [],\n  "watchlist": [], "quality_warnings": []\n}}\n```\n`themes` 必须覆盖且只使用这六个主题：生产与供给、需求与收入、价格与利润、货币与信用、财政与房地产、外部平衡。每个主题都必须回答：\n- `data_facts`：关键数据事实（含指标 ID、统计期、数值、单位、source）；\n- `what_data_indicates`：数据直接表明什么；\n- `cross_theme_links`：与其他主题的关联及其数据依据；\n- `logic_chain`：按“数据变化 → 直接含义 → 传导机制 → 可能影响”分步写；\n- `future_implications`：使用条件句说明可能的未来变化和影响；\n- `supporting_evidence`、`counter_evidence`、`unknowns`、`watchlist`、`data_refs`。\n\n同时输出一份面向人的 Markdown 分析，顺序为：一句话总览、六主题状态（每个主题包含数据事实、数据表明什么、跨领域关联、逻辑链、未来影响、证据、无法判断、后续观察）、相互印证与背离、当前无法判断、下月观察清单、数据口径与质量说明。\n"""
    _write(target / "analysis-prompt.md", prompt)
    package_seed = json.dumps(
        {"period": period, "observations": facts["observations"], "history": facts["history"], "missing": missing},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    package_id = hashlib.sha256(package_seed).hexdigest()[:16]
    manifest = {"package_id": package_id, "period": period, "files": ["facts.json", "evidence.md", "quality-report.md", "indicator-definitions.md", "analysis-prompt.md"], "observation_count": len(points), "history_observation_count": len(history_points), "missing_count": len(missing), "quality_issue_count": len(quality.issues)}
    (target / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = target.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in [*manifest["files"], "manifest.json"]:
            bundle.write(target / name, arcname=name)
    return target


def generate_agent_context_from_config(period: str, *, data_root: Path | str = Path("data"), output_dir: Path | str = DEFAULT_AGENT_EXPORT_DIR) -> Path:
    indicators, _, _ = validate_config(Path(__file__).resolve().parents[1] / "config")
    root = Path(data_root)
    current = load_period_points(root, period)
    history = _history_points(root, period)
    return generate_agent_context(period, current, indicators, output_dir=output_dir, history_points=history)
