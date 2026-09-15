#!/usr/bin/env python3
"""
agent-cost-logger — summarize AI API spend from JSONL logs.

Created and maintained by Moneymaker, an AI agent working for Ray Malhotra.
Human review welcome. Review and adapt before production use.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

# Simple fallback rates (USD per 1M tokens) when "usd" is missing.
# Documented in README — adjust to your provider's pricing.
DEFAULT_RATES_PER_1M = {
    "gpt-4o": {"in": 2.50, "out": 10.00},
    "gpt-4o-mini": {"in": 0.15, "out": 0.60},
    "claude-sonnet": {"in": 3.00, "out": 15.00},
    "claude-haiku": {"in": 0.80, "out": 4.00},
    "gemini-flash": {"in": 0.10, "out": 0.40},
    "default": {"in": 1.00, "out": 3.00},
}


def estimate_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    key = (model or "").strip().lower()
    rates = DEFAULT_RATES_PER_1M.get(key, DEFAULT_RATES_PER_1M["default"])
    return (tokens_in / 1_000_000.0) * rates["in"] + (tokens_out / 1_000_000.0) * rates["out"]


def parse_timestamp(value: str) -> datetime:
    """Parse ISO-8601 timestamps; assume UTC if naive."""
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def load_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            for required in ("timestamp", "model", "tokens_in", "tokens_out"):
                if required not in obj:
                    raise SystemExit(f"{path}:{lineno}: missing field '{required}'")
            try:
                ts = parse_timestamp(str(obj["timestamp"]))
                tokens_in = int(obj["tokens_in"])
                tokens_out = int(obj["tokens_out"])
            except (TypeError, ValueError) as exc:
                raise SystemExit(f"{path}:{lineno}: bad field types: {exc}") from exc
            if "usd" in obj and obj["usd"] is not None:
                try:
                    usd = float(obj["usd"])
                    usd_estimated = False
                except (TypeError, ValueError) as exc:
                    raise SystemExit(f"{path}:{lineno}: bad usd: {exc}") from exc
            else:
                usd = estimate_usd(str(obj["model"]), tokens_in, tokens_out)
                usd_estimated = True
            rows.append(
                {
                    "timestamp": ts,
                    "model": str(obj["model"]),
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "usd": usd,
                    "usd_estimated": usd_estimated,
                }
            )
    return rows


def iso_day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def iso_week(dt: datetime) -> str:
    # ISO week: YYYY-Www
    year, week, _ = dt.isocalendar()
    return f"{year}-W{week:02d}"


def aggregate(
    rows: Iterable[Dict[str, Any]], keyfn
) -> Dict[str, Dict[str, float]]:
    buckets: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"tokens_in": 0.0, "tokens_out": 0.0, "usd": 0.0, "rows": 0.0, "estimated": 0.0}
    )
    for row in rows:
        k = keyfn(row["timestamp"])
        b = buckets[k]
        b["tokens_in"] += row["tokens_in"]
        b["tokens_out"] += row["tokens_out"]
        b["usd"] += row["usd"]
        b["rows"] += 1
        if row["usd_estimated"]:
            b["estimated"] += 1
    return dict(sorted(buckets.items()))


def print_section(title: str, buckets: Dict[str, Dict[str, float]]) -> None:
    print(f"\n=== {title} ===")
    if not buckets:
        print("(no rows)")
        return
    print(f"{'bucket':<12} {'rows':>6} {'tok_in':>10} {'tok_out':>10} {'usd':>10} {'est':>5}")
    for key, b in buckets.items():
        est = int(b["estimated"])
        print(
            f"{key:<12} {int(b['rows']):>6} {int(b['tokens_in']):>10} "
            f"{int(b['tokens_out']):>10} ${b['usd']:>9.4f} {est:>5}"
        )


def print_totals(rows: List[Dict[str, Any]]) -> None:
    total_in = sum(r["tokens_in"] for r in rows)
    total_out = sum(r["tokens_out"] for r in rows)
    total_usd = sum(r["usd"] for r in rows)
    estimated = sum(1 for r in rows if r["usd_estimated"])
    print("\n=== Totals ===")
    print(f"Rows:        {len(rows)}")
    print(f"Tokens in:   {total_in}")
    print(f"Tokens out:  {total_out}")
    print(f"USD:         ${total_usd:.4f}")
    print(f"Estimated:   {estimated} row(s) used fallback rates")


def cmd_summarize(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 1
    rows = load_rows(path)
    if args.since:
        since = parse_timestamp(args.since)
        rows = [r for r in rows if r["timestamp"] >= since]
    print_totals(rows)
    if args.by in ("day", "all"):
        print_section("By day", aggregate(rows, iso_day))
    if args.by in ("week", "all"):
        print_section("By week", aggregate(rows, iso_week))
    if args.by_model:
        model_buckets: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {"tokens_in": 0.0, "tokens_out": 0.0, "usd": 0.0, "rows": 0.0, "estimated": 0.0}
        )
        for row in rows:
            b = model_buckets[row["model"]]
            b["tokens_in"] += row["tokens_in"]
            b["tokens_out"] += row["tokens_out"]
            b["usd"] += row["usd"]
            b["rows"] += 1
            if row["usd_estimated"]:
                b["estimated"] += 1
        print_section("By model", dict(sorted(model_buckets.items())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cost_logger.py",
        description=(
            "Summarize AI API spend from JSONL logs. "
            "Each line: {timestamp, model, tokens_in, tokens_out, usd?}."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    summarize = sub.add_parser(
        "summarize",
        help="Print totals and breakdowns by day and/or week",
    )
    summarize.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to JSONL spend log",
    )
    summarize.add_argument(
        "--by",
        choices=("day", "week", "all"),
        default="all",
        help="Breakdown mode (default: all)",
    )
    summarize.add_argument(
        "--by-model",
        action="store_true",
        help="Also group totals by model name",
    )
    summarize.add_argument(
        "--since",
        help="Only include rows on/after this ISO timestamp",
    )
    summarize.set_defaults(func=cmd_summarize)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
