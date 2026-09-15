#!/usr/bin/env python3
"""Minimal stdlib tests for agent-cost-logger (example_data.jsonl)."""

from __future__ import annotations

import csv
import io
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import cost_logger as cl

ROOT = Path(__file__).resolve().parent
EXAMPLE = ROOT / "example_data.jsonl"


class TestSummarizeTotals(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = cl.load_rows(EXAMPLE)

    def test_row_count(self) -> None:
        self.assertEqual(len(self.rows), 20)

    def test_token_totals(self) -> None:
        self.assertEqual(sum(r["tokens_in"] for r in self.rows), 481_000)
        self.assertEqual(sum(r["tokens_out"] for r in self.rows), 118_500)

    def test_usd_total(self) -> None:
        total_usd = sum(r["usd"] for r in self.rows)
        self.assertAlmostEqual(total_usd, 1.4502, places=4)

    def test_estimated_count(self) -> None:
        estimated = sum(1 for r in self.rows if r["usd_estimated"])
        self.assertEqual(estimated, 7)

    def test_day_and_week_buckets(self) -> None:
        by_day = cl.aggregate(self.rows, cl.iso_day)
        by_week = cl.aggregate(self.rows, cl.iso_week)
        self.assertEqual(len(by_day), 12)
        self.assertEqual(set(by_week), {"2026-W36", "2026-W37"})
        self.assertEqual(int(by_week["2026-W36"]["rows"]), 12)
        self.assertEqual(int(by_week["2026-W37"]["rows"]), 8)


class TestExportCsv(unittest.TestCase):
    def test_export_csv_header_and_sections(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w+", encoding="utf-8", suffix=".csv", delete=False
        ) as tmp:
            out_path = tmp.name
        try:
            args = Namespace(
                file=str(EXAMPLE),
                by="all",
                by_model=False,
                since=None,
                output=out_path,
            )
            self.assertEqual(cl.cmd_export(args), 0)
            with open(out_path, encoding="utf-8", newline="") as fh:
                reader = csv.DictReader(fh)
                self.assertEqual(list(reader.fieldnames or []), list(cl.CSV_FIELDS))
                rows = list(reader)
        finally:
            Path(out_path).unlink(missing_ok=True)

        sections = {r["section"] for r in rows}
        self.assertEqual(sections, {"day", "week", "model"})
        self.assertGreaterEqual(len(rows), 12 + 2 + 5)  # days + weeks + models

        day_0901 = next(r for r in rows if r["section"] == "day" and r["bucket"] == "2026-09-01")
        self.assertEqual(day_0901["rows"], "2")
        self.assertEqual(day_0901["tokens_in"], "20000")
        self.assertEqual(day_0901["tokens_out"], "5000")

        week_36 = next(r for r in rows if r["section"] == "week" and r["bucket"] == "2026-W36")
        self.assertEqual(week_36["rows"], "12")

    def test_write_csv_buckets_roundtrip(self) -> None:
        rows = cl.load_rows(EXAMPLE)
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=cl.CSV_FIELDS)
        writer.writeheader()
        cl.write_csv_buckets(writer, "model", cl.model_aggregate(rows))
        buf.seek(0)
        parsed = list(csv.DictReader(buf))
        models = {r["bucket"] for r in parsed}
        self.assertIn("gpt-4o", models)
        self.assertIn("gpt-4o-mini", models)
        self.assertEqual(len(parsed), 5)


if __name__ == "__main__":
    unittest.main()
