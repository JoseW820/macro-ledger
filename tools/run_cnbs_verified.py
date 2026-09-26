"""Run the confirmed cnbs payloads supplied by a host client.

The host must provide a JSON payload file exported from cnbs. This utility is
deliberately offline: it proves normalization and archival without embedding
MCP credentials or depending on Codex internals.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import load_confirmed_nbs_codes, load_indicators
from app.providers.cnbs import CnbsProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--indicator", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--data-root", default="data")
    args = parser.parse_args()
    config_dir = Path(__file__).resolve().parents[1] / "config"
    definitions = {item.indicator_id: item for item in load_indicators(config_dir)}
    confirmed = load_confirmed_nbs_codes(config_dir)
    if args.indicator not in definitions:
        parser.error(f"未知指标: {args.indicator}")
    if args.indicator not in confirmed:
        parser.error(f"指标没有经过确认代码登记: {args.indicator}")
    payload = json.loads(args.payload.read_text(encoding="utf-8"))
    result = CnbsProvider(data_root=args.data_root).fetch_search_payload(definitions[args.indicator], args.period, payload)
    print(json.dumps({"indicator_id": args.indicator, "period": args.period, "status": result.status, "points": [point.__dict__ for point in result.points], "raw_artifact": result.raw_artifact, "metadata": result.metadata}, ensure_ascii=False, indent=2, default=str))
    return 0 if result.status == "success" else 2


if __name__ == "__main__":
    raise SystemExit(main())
