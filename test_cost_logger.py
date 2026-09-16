#!/usr/bin/env python3
"""Minimal stdlib tests for agent-cost-logger (example_data.jsonl)."""

from __future__ import annotations

import csv
import json
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



class TestBudget(unittest.TestCase):
    def test_under_budget_all(self) -> None:
        args = Namespace(file=str(EXAMPLE), limit=2.00, period="all", since=None)
        self.assertEqual(cl.cmd_budget(args), 0)

    def test_over_budget_all(self) -> None:
        args = Namespace(file=str(EXAMPLE), limit=1.00, period="all", since=None)
        self.assertEqual(cl.cmd_budget(args), 1)

    def test_exact_limit_is_under(self) -> None:
        # spent == limit counts as UNDER (exit 0)
        args = Namespace(file=str(EXAMPLE), limit=1.4502, period="all", since=None)
        self.assertEqual(cl.cmd_budget(args), 0)

    def test_period_day_latest_in_log(self) -> None:
        # Latest day in example_data is 2026-09-12 (~$0.00387)
        args = Namespace(file=str(EXAMPLE), limit=0.01, period="day", since=None)
        self.assertEqual(cl.cmd_budget(args), 0)
        args_over = Namespace(file=str(EXAMPLE), limit=0.001, period="day", since=None)
        self.assertEqual(cl.cmd_budget(args_over), 1)

    def test_period_week_latest_in_log(self) -> None:
        # Latest week is 2026-W37 (~$0.66042)
        args = Namespace(file=str(EXAMPLE), limit=1.00, period="week", since=None)
        self.assertEqual(cl.cmd_budget(args), 0)
        args_over = Namespace(file=str(EXAMPLE), limit=0.50, period="week", since=None)
        self.assertEqual(cl.cmd_budget(args_over), 1)

    def test_bad_limit_exit_2(self) -> None:
        args = Namespace(file=str(EXAMPLE), limit=0, period="all", since=None)
        self.assertEqual(cl.cmd_budget(args), 2)
        args_neg = Namespace(file=str(EXAMPLE), limit=-1.0, period="all", since=None)
        self.assertEqual(cl.cmd_budget(args_neg), 2)

    def test_missing_file_exit_2(self) -> None:
        args = Namespace(file=str(ROOT / "no_such_file.jsonl"), limit=1.0, period="all", since=None)
        self.assertEqual(cl.cmd_budget(args), 2)

    def test_select_budget_rows_helpers(self) -> None:
        rows = cl.load_rows(EXAMPLE)
        label, selected = cl.select_budget_rows(rows, "day")
        self.assertEqual(label, "day 2026-09-12")
        self.assertEqual(len(selected), 1)
        self.assertAlmostEqual(sum(r["usd"] for r in selected), 0.00387, places=5)
        wlabel, wsel = cl.select_budget_rows(rows, "week")
        self.assertEqual(wlabel, "week 2026-W37")
        self.assertEqual(len(wsel), 8)




class TestAppend(unittest.TestCase):
    def test_append_creates_file_with_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "nested" / "spend.jsonl"
            args = Namespace(
                file=str(log_path),
                model="gpt-4o-mini",
                tokens_in=1000,
                tokens_out=200,
                usd=None,
                timestamp="2026-09-16T12:00:00Z",
                print=False,
            )
            self.assertEqual(cl.cmd_append(args), 0)
            self.assertTrue(log_path.is_file())
            lines = log_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            obj = json.loads(lines[0])
            self.assertEqual(obj["timestamp"], "2026-09-16T12:00:00Z")
            self.assertEqual(obj["model"], "gpt-4o-mini")
            self.assertEqual(obj["tokens_in"], 1000)
            self.assertEqual(obj["tokens_out"], 200)
            self.assertNotIn("usd", obj)

    def test_append_with_usd_includes_usd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "spend.jsonl"
            args = Namespace(
                file=str(log_path),
                model="gpt-4o",
                tokens_in=10,
                tokens_out=5,
                usd=0.0123,
                timestamp="2026-09-16T12:00:00Z",
                print=False,
            )
            self.assertEqual(cl.cmd_append(args), 0)
            obj = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertIn("usd", obj)
            self.assertAlmostEqual(obj["usd"], 0.0123)

    def test_append_without_usd_omits_usd_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "spend.jsonl"
            args = Namespace(
                file=str(log_path),
                model="claude-haiku",
                tokens_in=0,
                tokens_out=0,
                usd=None,
                timestamp="2026-09-16T12:00:00Z",
                print=False,
            )
            self.assertEqual(cl.cmd_append(args), 0)
            obj = json.loads(log_path.read_text(encoding="utf-8").strip())
            self.assertNotIn("usd", obj)

    def test_append_negative_tokens_exit_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "spend.jsonl"
            args = Namespace(
                file=str(log_path),
                model="gpt-4o",
                tokens_in=-1,
                tokens_out=5,
                usd=None,
                timestamp=None,
                print=False,
            )
            self.assertEqual(cl.cmd_append(args), 2)
            self.assertFalse(log_path.exists())
            args2 = Namespace(
                file=str(log_path),
                model="gpt-4o",
                tokens_in=1,
                tokens_out=-5,
                usd=None,
                timestamp=None,
                print=False,
            )
            self.assertEqual(cl.cmd_append(args2), 2)
            self.assertFalse(log_path.exists())



if __name__ == "__main__":
    unittest.main()
