"""Deterministic HTML and Excel report generation from audited observations."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.models import DataPoint
from app.analysis.quality import QualityReport, check_points


def _value(point: DataPoint) -> str:
    return "当前无法判断" if point.value is None else f"{point.value} {point.unit}"


def generate_html(period: str, points: Iterable[DataPoint], *, quality: QualityReport | None = None, analysis: dict[str, object] | None = None, output_dir: Path | str = Path("reports")) -> Path:
    rows = list(points)
    quality = quality or check_points(rows)
    core = [p for p in rows if p.indicator_id and p.value is not None]
    body = "".join(f"<tr><td>{html.escape(p.indicator_name)}</td><td>{html.escape(p.period)}</td><td>{html.escape(_value(p))}</td><td>{html.escape(p.source)}</td><td>{html.escape(p.source_url or '未提供')}</td></tr>" for p in core)
    issues = "".join(f"<li>{html.escape(issue.code)}：{html.escape(issue.message)}</li>" for issue in quality.issues) or "<li>未发现已配置检查项问题</li>"
    analysis_block = "<h2>宏观状态</h2><p>数据已整理，尚未导入并确认 AI 分析结果。</p>"
    if isinstance(analysis, dict):
        regime = analysis.get("macro_regime")
        regime = regime if isinstance(regime, dict) else {}
        label = html.escape(str(regime.get("label") or "当前无法判断"))
        confidence = html.escape(str(regime.get("confidence") or "未提供"))
        overview = html.escape(str(regime.get("summary") or analysis.get("overview") or "当前无法判断"))
        theme_rows: list[str] = []
        themes = analysis.get("themes")
        if isinstance(themes, dict):
            for key, item in themes.items():
                if isinstance(item, dict):
                    detail_parts = [
                        str(item.get("what_data_indicates") or item.get("conclusion") or ""),
                        str(item.get("summary") or ""),
                        "数据事实：" + "；".join(str(value) for value in (item.get("data_facts") or [])),
                        "跨领域关联：" + "；".join(str(value.get("theme", "")) + "：" + str(value.get("relationship", "")) if isinstance(value, dict) else str(value) for value in (item.get("cross_theme_links") or [])),
                        "逻辑链：" + " → ".join(str(value) for value in (item.get("logic_chain") or [])),
                        "未来影响：" + "；".join(str(value) for value in (item.get("future_implications") or [])),
                        "支持证据：" + "；".join(str(value) for value in (item.get("supporting_evidence") or [])),
                        "无法判断：" + "；".join(str(value) for value in (item.get("unknowns") or [])),
                        "后续观察：" + "；".join(str(value) for value in (item.get("watchlist") or [])),
                    ]
                    detail = "<br>".join(html.escape(value) for value in detail_parts if value.strip()) or "当前无法判断"
                    theme_rows.append(f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(item.get('status') or '当前无法判断'))}</td><td>{detail}</td></tr>")
        contradictions = analysis.get("contradictions") if isinstance(analysis.get("contradictions"), list) else []
        unknowns = analysis.get("unknowns") if isinstance(analysis.get("unknowns"), list) else []
        watchlist = analysis.get("watchlist") if isinstance(analysis.get("watchlist"), list) else []
        def list_block(values: list[object]) -> str:
            return "".join(f"<li>{html.escape(str(value))}</li>" for value in values) or "<li>暂无</li>"
        analysis_block = f"<h2>宏观状态（已确认 AI 分析）</h2><p><strong>{label}</strong>　<span class=muted>置信度：{confidence}</span></p><p>{overview}</p><table><thead><tr><th>主题</th><th>状态</th><th>证据与判断</th></tr></thead><tbody>{''.join(theme_rows) or '<tr><td colspan=3>当前无法判断</td></tr>'}</tbody></table><h3>相互印证与背离</h3><ul>{list_block(contradictions)}</ul><h3>当前无法判断</h3><ul>{list_block(unknowns)}</ul><h3>下月观察清单</h3><ul>{list_block(watchlist)}</ul>"
    content = f"""<!doctype html><html lang=zh-CN><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>宏观数据月报 {html.escape(period)}</title><style>body{{font-family:system-ui,sans-serif;max-width:1200px;margin:auto;padding:20px;color:#20252b}}table{{width:100%;border-collapse:collapse}}th,td{{border-bottom:1px solid #ddd;padding:8px;text-align:left}}.muted{{color:#68717b}}@media(max-width:700px){{body{{padding:12px}}table{{font-size:12px}}}}</style><h1>宏观数据观察月报</h1><p class=muted>报告期：{html.escape(period)}　生成时间：{datetime.now(timezone.utc).isoformat(timespec='seconds')}</p>{analysis_block}<h2>数据矩阵</h2><table><thead><tr><th>指标</th><th>统计期</th><th>数值</th><th>来源</th><th>来源链接</th></tr></thead><tbody>{body}</tbody></table><h2>质量提示</h2><ul>{issues}</ul><h2>分析边界</h2><p>本页面只展示已审计观测。缺失数据不填充为零，不构造买卖建议；没有足够证据的主题结论显示为“当前无法判断”。</p></html>"""
    target = Path(output_dir) / period / "monthly-report.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def generate_excel(period: str, points: Iterable[DataPoint], *, output_dir: Path | str = Path("reports")) -> Path:
    try:
        from openpyxl import Workbook
    except ImportError as exc:
        raise RuntimeError("生成 Excel 需要安装 openpyxl：pip install -e .[spreadsheets]") from exc
    target = Path(output_dir) / period / "data-matrix.xlsx"
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据矩阵"
    sheet.append(["指标ID", "指标", "统计期", "数值", "单位", "频率", "来源", "来源链接", "质量状态"])
    for point in points:
        sheet.append([point.indicator_id, point.indicator_name, point.period, point.value, point.unit, point.frequency, point.source, point.source_url, point.quality_status])
    workbook.save(target)
    return target
