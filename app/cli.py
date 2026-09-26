"""Command-line entry point for the phase-one project skeleton."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ConfigError, validate_config
from .models import RunSummary
from .pipeline.fetch import ProviderRegistry, fetch_indicators
from .providers.cnbs import CnbsProvider
from .providers.customs import CustomsProvider
from .providers.international import InternationalProvider
from .providers.mof import MOFProvider
from .providers.nbs import NBSProvider
from .providers.nbs_file import NBSFileProvider
from .providers.pboc import PBOCProvider
from .providers.rates import RatesProvider
from .providers.safe import SAFEProvider
from .providers.official import configured_endpoint_fetcher
from .providers.source_catalog import OFFICIAL_ENTRYPOINTS, check_source
from .storage.sqlite import SQLiteStore
from .report.generator import generate_html, generate_excel
from .agent_context import DEFAULT_AGENT_EXPORT_DIR, generate_agent_context_from_config
from .pipeline.normalized import load_period_points


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Macro Ledger 本地宏观数据台账工具")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-indicators", help="列出已配置指标")
    subparsers.add_parser("validate-config", help="验证指标、数据源和发布时间配置")

    run_parser = subparsers.add_parser("run", help="运行一次采集流程")
    run_parser.add_argument("--period", required=True, help="统计期，例如 2026-08")
    run_parser.add_argument("--dry-run", action="store_true", help="只显示计划，不联网、不写入正式数据")
    run_parser.add_argument("--only", action="append", help="只采集指定 indicator_id，可重复传入")
    run_parser.add_argument("--nbs-code", action="append", help="经确认的 NBS 代码，格式为 indicator_id=code，可重复传入")
    run_parser.add_argument("--data-root", default="data", help="原始和标准化数据目录")

    import_parser = subparsers.add_parser("import-nbs-file", help="导入国家统计局官方导出的 CSV/JSON 文件")
    import_parser.add_argument("--indicator", required=True, help="指标 indicator_id")
    import_parser.add_argument("--period", required=True, help="统计期，例如 2026-08")
    import_parser.add_argument("--file", required=True, help="官方导出的 CSV 或 JSON 文件")
    import_parser.add_argument("--data-root", default="data", help="原始和标准化数据目录")
    subparsers.add_parser("check-official-sources", help="测试人民银行、海关、外汇局、财政部官网连通性")
    subparsers.add_parser("doctor", help="检查配置、依赖和密钥状态")
    status_parser = subparsers.add_parser("status", help="查看某期数据和报告状态")
    status_parser.add_argument("--period", required=True)
    status_parser.add_argument("--data-root", default="data", help="数据目录")
    web_parser = subparsers.add_parser("web", help="启动本地报告网页")
    web_parser.add_argument("--host", default="127.0.0.1")
    web_parser.add_argument("--port", type=int, default=8765)
    web_parser.add_argument("--data-root", default="data", help="数据目录")
    report_parser = subparsers.add_parser("report", help="生成 HTML 月报和 Excel 数据矩阵")
    report_parser.add_argument("--period", required=True, help="报告期，例如 2026-08")
    report_parser.add_argument("--data-root", default="data", help="标准化数据目录")
    report_parser.add_argument("--output-dir", default="reports", help="报告输出目录")
    agent_parser = subparsers.add_parser("agent-context", help="生成给外部 AI Agent 使用的审计分析包")
    agent_parser.add_argument("--period", required=True, help="统计期，例如 2026-08")
    agent_parser.add_argument("--data-root", default="data", help="标准化数据目录")
    agent_parser.add_argument("--output-dir", default=str(DEFAULT_AGENT_EXPORT_DIR), help="Agent 分析包输出目录")
    return parser


def _validate_period(period: str) -> None:
    if len(period) != 7 or period[4] != "-" or not period[:4].isdigit() or not period[5:].isdigit():
        raise ConfigError(f"统计期必须是 YYYY-MM，例如 2026-08: {period}")
    month = int(period[5:])
    if month < 1 or month > 12:
        raise ConfigError(f"统计期月份无效: {period}")


def _load() -> tuple[list, dict, dict]:
    return validate_config(CONFIG_DIR)


def _list_indicators() -> int:
    indicators, _, _ = _load()
    print(f"已配置 {len(indicators)} 项指标")
    for item in indicators:
        core = "核心" if item.homepage_core else "专题"
        print(f"- {item.indicator_id}: {item.name} [{item.frequency}, {item.unit}, {core}]")
    return 0


def _validate_config() -> int:
    indicators, sources, calendar = _load()
    print(f"配置有效：{len(indicators)} 项指标，{len(sources)} 个数据源，{len(calendar['rules'])} 条发布时间规则")
    return 0


def _dry_run(period: str) -> int:
    _validate_period(period)
    indicators, sources, _ = _load()
    summary = RunSummary(period=period, dry_run=True, planned_indicators=len(indicators))
    print(f"统计期: {summary.period}")
    print(f"模式: dry-run（不会联网，不写入正式数据）")
    print(f"计划指标: {summary.planned_indicators}")
    print("采集计划:")
    for item in indicators:
        source = item.primary_source
        source_name = sources[source].get("name", source)
        fallbacks = ", ".join(item.fallback_sources) or "无"
        print(f"- {item.indicator_id}: {source_name}；备用来源: {fallbacks}")
    return 0


def _parse_nbs_codes(items: list[str] | None) -> dict[str, str]:
    codes: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise ConfigError(f"--nbs-code 必须是 indicator_id=code: {item}")
        indicator_id, code = item.split("=", 1)
        if not indicator_id.strip() or not code.strip():
            raise ConfigError(f"--nbs-code 不能为空: {item}")
        codes[indicator_id.strip()] = code.strip()
    return codes


def _collect(period: str, only: list[str] | None, nbs_codes: list[str] | None, data_root: str) -> int:
    _validate_period(period)
    indicators, sources, _ = _load()
    selected = indicators
    if only:
        wanted = set(only)
        selected = [item for item in indicators if item.indicator_id in wanted]
        unknown = wanted - {item.indicator_id for item in selected}
        if unknown:
            raise ConfigError(f"未知 indicator_id: {', '.join(sorted(unknown))}")
    code_map = dict(sources.get("nbs", {}).get("series_codes", {}))
    code_map.update(_parse_nbs_codes(nbs_codes))
    nbs_base_url = sources.get("nbs", {}).get("base_url", "https://data.stats.gov.cn/easyquery.htm")
    registry = ProviderRegistry(
        {
            "nbs": NBSProvider(base_url=nbs_base_url, code_map=code_map, data_root=Path(data_root)),
            "cnbs": CnbsProvider(data_root=Path(data_root)),
            "pboc": PBOCProvider(fetcher=configured_endpoint_fetcher("PBOC_OFFICIAL_ENDPOINT"), data_root=Path(data_root)),
            "customs": CustomsProvider(fetcher=configured_endpoint_fetcher("CUSTOMS_OFFICIAL_ENDPOINT"), data_root=Path(data_root)),
            "safe": SAFEProvider(fetcher=configured_endpoint_fetcher("SAFE_OFFICIAL_ENDPOINT"), data_root=Path(data_root)),
            "mof": MOFProvider(fetcher=configured_endpoint_fetcher("MOF_OFFICIAL_ENDPOINT"), data_root=Path(data_root)),
            "rates": RatesProvider(data_root=Path(data_root)),
            "fred": InternationalProvider(data_root=Path(data_root)),
        }
    )
    store = SQLiteStore(Path(data_root) / "macro_observer.sqlite")
    run_id = store.run_start(period, provider="pipeline")
    for indicator in selected:
        store.upsert_definition(indicator, updated_at=__import__("datetime").datetime.now().isoformat(timespec="seconds"))
    try:
        results, summary = fetch_indicators(selected, period, registry, normalized_root=Path(data_root) / "normalized")
        for result in results:
            if result.status == "success":
                store.insert_fetch_result(result, provider=result.points[0].source if result.points else None)
            else:
                for issue in summary.issues:
                    if issue.indicator_id == result.indicator.indicator_id:
                        store.insert_issue(issue)
        store.run_finish(run_id, status="success" if summary.failed == 0 else "partial_failure", summary={"planned": summary.planned_indicators, "completed": summary.completed, "failed": summary.failed})
    except Exception as exc:
        store.run_finish(run_id, status="error", summary={"error": str(exc)})
        store.close()
        raise
    store.close()
    print(f"统计期: {summary.period}")
    print(f"采集完成: {summary.completed}/{summary.planned_indicators}；失败: {summary.failed}")
    for result in results:
        suffix = f"；{result.errors[0]}" if result.errors else ""
        print(f"- {result.indicator.indicator_id}: {result.status}{suffix}")
    return 0 if summary.failed == 0 else 2


def _import_nbs_file(indicator_id: str, period: str, file_path: str, data_root: str) -> int:
    _validate_period(period)
    indicators, _, _ = _load()
    indicator = next((item for item in indicators if item.indicator_id == indicator_id), None)
    if indicator is None:
        raise ConfigError(f"未知 indicator_id: {indicator_id}")
    result = NBSFileProvider(data_root=Path(data_root)).fetch(indicator, period, file_path)
    print(f"指标: {indicator.name} ({indicator.indicator_id})")
    print(f"统计期: {period}")
    print(f"导入结果: {result.status}")
    for point in result.points:
        print(f"- {point.period}: {point.value} {point.unit} [{point.source}]")
    for error in result.errors:
        print(f"- {error}")
    if result.raw_artifact:
        print(f"原始快照: {result.raw_artifact}")
    normalized = result.metadata.get("normalized_artifact")
    if normalized:
        print(f"标准化文件: {normalized}")
    return 0 if result.status == "success" else 2


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    try:
        if args.command == "list-indicators":
            return _list_indicators()
        if args.command == "validate-config":
            return _validate_config()
        if args.command == "run":
            if args.dry_run:
                return _dry_run(args.period)
            return _collect(args.period, args.only, args.nbs_code, args.data_root)
        if args.command == "import-nbs-file":
            return _import_nbs_file(args.indicator, args.period, args.file, args.data_root)
        if args.command == "check-official-sources":
            failures = 0
            for source, url in OFFICIAL_ENTRYPOINTS.items():
                result = check_source(source, url)
                if result.status is None:
                    failures += 1
                    print(f"{source}: ERROR {result.error}")
                else:
                    print(f"{source}: HTTP {result.status} {result.content_type} {url}")
            return 0 if failures == 0 else 2
        if args.command == "doctor":
            checks = []
            try:
                validate_config(CONFIG_DIR)
                checks.append(("配置", "通过"))
            except ConfigError as exc:
                checks.append(("配置", f"失败：{exc}"))
            checks.append(("FRED_API_KEY", "已配置" if __import__("os").getenv("FRED_API_KEY") else "未配置（国际数据不可用）"))
            try:
                import openpyxl  # noqa: F401
                checks.append(("openpyxl", "已安装"))
            except ImportError:
                checks.append(("openpyxl", "未安装（Excel 功能不可用）"))
            for name, status in checks:
                print(f"{name}: {status}")
            return 0
        if args.command == "status":
            _validate_period(args.period)
            normalized = list((Path(args.data_root) / "normalized").glob(f"*/{args.period}/*.json"))
            reports = list((Path("reports") / args.period).glob("*"))
            print(f"统计期: {args.period}")
            print(f"标准化数据文件: {len(normalized)}")
            print(f"报告文件: {len(reports)}")
            return 0
        if args.command == "web":
            from .web import serve
            serve(args.host, args.port, data_root=args.data_root)
            return 0
        if args.command == "report":
            _validate_period(args.period)
            points = load_period_points(args.data_root, args.period)
            store = SQLiteStore(Path(args.data_root) / "macro_observer.sqlite")
            analysis = None
            for row in store.analyses(period=args.period):
                if row["status"] == "confirmed":
                    try:
                        candidate = json.loads(row["result_json"])
                        analysis = candidate if isinstance(candidate, dict) else None
                    except (TypeError, json.JSONDecodeError):
                        analysis = None
                    break
            store.close()
            html_path = generate_html(args.period, points, analysis=analysis, output_dir=args.output_dir)
            excel_path = generate_excel(args.period, points, output_dir=args.output_dir)
            print(f"HTML: {html_path}")
            print(f"Excel: {excel_path}")
            return 0
        if args.command == "agent-context":
            _validate_period(args.period)
            target = generate_agent_context_from_config(args.period, data_root=args.data_root, output_dir=args.output_dir)
            print(f"Agent 分析包: {target}")
            print(f"事实文件: {target / 'facts.json'}")
            print(f"分析提示词: {target / 'analysis-prompt.md'}")
            return 0
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
