#!/usr/bin/env python3
"""
agent-cost-logger — summarize AI API spend from JSONL logs.

Created and maintained by Moneymaker, an AI agent working for Ray Malhotra.
Human review welcome. Review and adapt before production use.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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


def model_aggregate(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
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
    return dict(sorted(model_buckets.items()))


CSV_FIELDS = ("section", "bucket", "rows", "tokens_in", "tokens_out", "usd", "estimated")


def write_csv_buckets(
    writer: csv.DictWriter, section: str, buckets: Dict[str, Dict[str, float]]
) -> None:
    for key, b in buckets.items():
        writer.writerow(
            {
                "section": section,
                "bucket": key,
                "rows": int(b["rows"]),
                "tokens_in": int(b["tokens_in"]),
                "tokens_out": int(b["tokens_out"]),
                "usd": f"{b['usd']:.6f}",
                "estimated": int(b["estimated"]),
            }
        )


def load_filtered_rows(args: argparse.Namespace) -> List[Dict[str, Any]]:
    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        raise SystemExit(1)
    rows = load_rows(path)
    if args.since:
        since = parse_timestamp(args.since)
        rows = [r for r in rows if r["timestamp"] >= since]
    return rows


def cmd_summarize(args: argparse.Namespace) -> int:
    rows = load_filtered_rows(args)
    print_totals(rows)
    if args.by in ("day", "all"):
        print_section("By day", aggregate(rows, iso_day))
    if args.by in ("week", "all"):
        print_section("By week", aggregate(rows, iso_week))
    if args.by_model:
        print_section("By model", model_aggregate(rows))
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """Write day/week/model summaries as CSV to stdout or --output file."""
    rows = load_filtered_rows(args)
    out_fh = open(args.output, "w", encoding="utf-8", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(out_fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        if args.by in ("day", "all"):
            write_csv_buckets(writer, "day", aggregate(rows, iso_day))
        if args.by in ("week", "all"):
            write_csv_buckets(writer, "week", aggregate(rows, iso_week))
        if args.by_model or args.by == "all":
            write_csv_buckets(writer, "model", model_aggregate(rows))
    finally:
        if args.output:
            out_fh.close()
    return 0



def select_budget_rows(rows: List[Dict[str, Any]], period: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Pick rows for the budget window.

    day/week use the latest timestamp present in *rows* (after --since),
    so checks are clock-independent and work with example_data.jsonl.
    """
    if period == "all":
        return "all", list(rows)
    latest = max(r["timestamp"] for r in rows)
    if period == "day":
        label = iso_day(latest)
        selected = [r for r in rows if iso_day(r["timestamp"]) == label]
        return f"day {label}", selected
    if period == "week":
        label = iso_week(latest)
        selected = [r for r in rows if iso_week(r["timestamp"]) == label]
        return f"week {label}", selected
    raise ValueError(f"unknown period: {period}")


def cmd_budget(args: argparse.Namespace) -> int:
    """Compare filtered spend to a USD limit; exit 1 when over budget."""
    if args.limit is None or args.limit <= 0:
        print("error: --limit must be a positive number (USD)", file=sys.stderr)
        return 2
    path = Path(args.file)
    if not path.is_file():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2
    try:
        rows = load_rows(path)
    except SystemExit as exc:
        # Treat parse/schema failures as usage/input errors (exit 2).
        code = exc.code
        msg = code if isinstance(code, str) else (str(code) if code else "")
        if msg:
            print(msg, file=sys.stderr)
        return 2
    if args.since:
        try:
            since = parse_timestamp(args.since)
        except (TypeError, ValueError) as exc:
            print(f"error: bad --since timestamp: {exc}", file=sys.stderr)
            return 2
        rows = [r for r in rows if r["timestamp"] >= since]
    if not rows:
        print("error: no rows to check (empty log or filtered out)", file=sys.stderr)
        return 2
    period_label, selected = select_budget_rows(rows, args.period)
    spent = sum(r["usd"] for r in selected)
    estimated = sum(1 for r in selected if r["usd_estimated"])
    limit = float(args.limit)
    remaining = limit - spent
    if remaining >= 0:
        status = "UNDER"
        delta_label = f"remaining ${remaining:.4f}"
        exit_code = 0
    else:
        status = "OVER"
        delta_label = f"overage ${-remaining:.4f}"
        exit_code = 1
    est_note = f"; {estimated} estimated row(s)" if estimated else "; no estimates"
    print(
        f"budget {status}: period={period_label} spent=${spent:.4f} "
        f"limit=${limit:.4f} {delta_label}{est_note}"
    )
    return exit_code



def cmd_append(args: argparse.Namespace) -> int:
    """Append one JSONL spend row; create parent dirs and file if needed."""
    model = (args.model or "").strip()
    if not model:
        print("error: --model must be a non-empty string", file=sys.stderr)
        return 2
    try:
        tokens_in = int(args.tokens_in)
        tokens_out = int(args.tokens_out)
    except (TypeError, ValueError) as exc:
        print(f"error: tokens must be integers: {exc}", file=sys.stderr)
        return 2
    if tokens_in < 0 or tokens_out < 0:
        print("error: --tokens-in and --tokens-out must be >= 0", file=sys.stderr)
        return 2

    usd = None
    if args.usd is not None:
        try:
            usd = float(args.usd)
        except (TypeError, ValueError) as exc:
            print(f"error: bad --usd: {exc}", file=sys.stderr)
            return 2
        if usd < 0:
            print("error: --usd must be >= 0", file=sys.stderr)
            return 2

    if args.timestamp:
        try:
            ts = parse_timestamp(args.timestamp)
            timestamp = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError) as exc:
            print(f"error: bad --timestamp: {exc}", file=sys.stderr)
            return 2
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    row: Dict[str, Any] = {
        "timestamp": timestamp,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
    }
    if usd is not None:
        row["usd"] = usd

    line = json.dumps(row, separators=(",", ":"), ensure_ascii=False) + "\n"
    path = Path(args.file)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError as exc:
        print(f"error: could not write {path}: {exc}", file=sys.stderr)
        return 2

    if args.print:
        sys.stdout.write(line)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cost_logger.py",
        description=(
            "Append and summarize AI API spend from JSONL logs. "
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

    export = sub.add_parser(
        "export",
        help="Write day/week/model summaries as CSV (stdout or --output)",
    )
    export.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to JSONL spend log",
    )
    export.add_argument(
        "--by",
        choices=("day", "week", "all"),
        default="all",
        help="Which sections to include (default: all = day+week+model)",
    )
    export.add_argument(
        "--by-model",
        action="store_true",
        help="Include model section when --by is day or week",
    )
    export.add_argument(
        "--since",
        help="Only include rows on/after this ISO timestamp",
    )
    export.add_argument(
        "--output",
        "-o",
        help="Write CSV to this path (default: stdout)",
    )
    export.set_defaults(func=cmd_export)

    budget = sub.add_parser(
        "budget",
        help="Check spend against a USD limit (exit 1 if over)",
    )
    budget.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to JSONL spend log",
    )
    budget.add_argument(
        "--limit",
        type=float,
        required=True,
        help="USD budget threshold (must be > 0)",
    )
    budget.add_argument(
        "--period",
        choices=("day", "week", "all"),
        default="all",
        help=(
            "Window to check (default: all). "
            "day/week use the latest timestamp present in the filtered log."
        ),
    )
    budget.add_argument(
        "--since",
        help="Only include rows on/after this ISO timestamp",
    )
    budget.set_defaults(func=cmd_budget)


    append = sub.add_parser(
        "append",
        aliases=["log"],
        help="Append one JSONL spend row (agent-loop friendly)",
    )
    append.add_argument(
        "--file",
        "-f",
        required=True,
        help="Path to JSONL spend log (created if missing)",
    )
    append.add_argument(
        "--model",
        required=True,
        help="Model name (non-empty)",
    )
    append.add_argument(
        "--tokens-in",
        type=int,
        required=True,
        dest="tokens_in",
        help="Input tokens (integer >= 0)",
    )
    append.add_argument(
        "--tokens-out",
        type=int,
        required=True,
        dest="tokens_out",
        help="Output tokens (integer >= 0)",
    )
    append.add_argument(
        "--usd",
        type=float,
        default=None,
        help="USD cost (omit to let summarize estimate)",
    )
    append.add_argument(
        "--timestamp",
        help="ISO-8601 timestamp (default: now UTC with Z)",
    )
    append.add_argument(
        "--print",
        action="store_true",
        help="Also print the written JSON line to stdout",
    )
    append.set_defaults(func=cmd_append)

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
