# agent-cost-logger

[![CI](https://github.com/ray0840/agent-cost-logger/actions/workflows/ci.yml/badge.svg)](https://github.com/ray0840/agent-cost-logger/actions/workflows/ci.yml)

**Summarize AI API spend from a simple JSONL log.** Stdlib-only Python CLI — no pip install required to run.

> **AI disclosure (front and center):** Created and maintained by **Moneymaker**, an AI agent working for **Ray Malhotra**. Human review is welcome. Review and adapt before production use.

## Why this exists

Solo builders running AI agents often lose track of token spend until the invoice hits. Provider dashboards help after the fact; a local append-only JSONL log is better for agent loops and weekly budget checks. Drop one JSON object per API call into a file; this CLI prints day/week/model totals so you can catch burn early.

## Requirements

- Python 3.9+ (stdlib only)

## Install

```bash
# Option A — run the script directly (no install)
git clone https://github.com/ray0840/agent-cost-logger.git
cd agent-cost-logger
python3 cost_logger.py --help

# Option B — editable install (optional)
pip install -e .
agent-cost-logger --help
```

## JSONL format

One JSON object per line:

```json
{"timestamp":"2026-09-10T09:00:00Z","model":"gpt-4o","tokens_in":45000,"tokens_out":12000,"usd":0.2325}
```

| Field | Required | Notes |
|-------|----------|-------|
| `timestamp` | yes | ISO-8601; naive times treated as UTC |
| `model` | yes | Used for grouping and fallback rates |
| `tokens_in` | yes | Integer |
| `tokens_out` | yes | Integer |
| `usd` | no | If omitted, estimated from built-in rates |

Blank lines and `#` comments are ignored.

## Fallback rates (USD per 1M tokens)

Used only when `usd` is missing:

| Model key | Input | Output |
|-----------|------:|-------:|
| `gpt-4o` | 2.50 | 10.00 |
| `gpt-4o-mini` | 0.15 | 0.60 |
| `claude-sonnet` | 3.00 | 15.00 |
| `claude-haiku` | 0.80 | 4.00 |
| `gemini-flash` | 0.10 | 0.40 |
| `default` (anything else) | 1.00 | 3.00 |

Edit `DEFAULT_RATES_PER_1M` in `cost_logger.py` to match your contracts. Estimates are labeled in the `est` column.

## Usage examples

```bash
# Help
python3 cost_logger.py --help

# Full summary (totals + by day + by week) on the sample log
python3 cost_logger.py summarize --file example_data.jsonl

# Day-only or week-only breakdown
python3 cost_logger.py summarize --file example_data.jsonl --by day
python3 cost_logger.py summarize --file example_data.jsonl --by week

# Also group by model
python3 cost_logger.py summarize --file example_data.jsonl --by-model

# Filter to rows on/after a timestamp
python3 cost_logger.py summarize --file example_data.jsonl --since 2026-09-08T00:00:00Z

# CSV export (day + week + model) to stdout
python3 cost_logger.py export --file example_data.jsonl

# CSV to a file; day-only; model section with --by-model
python3 cost_logger.py export --file example_data.jsonl -o spend.csv
python3 cost_logger.py export --file example_data.jsonl --by day
python3 cost_logger.py export --file example_data.jsonl --by week --by-model
```

CSV columns: `section`, `bucket`, `rows`, `tokens_in`, `tokens_out`, `usd`, `estimated`.
With `--by all` (default), `section` is `day`, `week`, and `model`.

Append a row from an agent wrapper:

```bash
echo '{"timestamp":"'"$(date -u +%Y-%m-%dT%H:%M:%SZ)"'","model":"gpt-4o-mini","tokens_in":1000,"tokens_out":200,"usd":0.00027}' >> spend.jsonl
```

Typical weekly habit: append from your agent loop, then run `summarize` once a week against a soft budget. If over, drop model tier or pause non-critical jobs.

## Same family (cross-links)

- **Solo AI Agent Operator Kit** (free sample + Pages landing): https://github.com/ray0840/solo-ai-agent-operator-kit · https://ray0840.github.io/solo-ai-agent-operator-kit/
- **VPS AI Agent Security Hardening Checklist** (free sample): https://github.com/ray0840/vps-ai-agent-security-checklist

## Notes

- Ops hygiene tool, **not** a billing system of record. Reconcile against provider invoices weekly.
- Never commit live API keys alongside your spend log.
- Sponsors / Polar tiers: see `docs/SPONSORS_DRAFT.md` (**draft only** — not live).

## License

MIT — see [`LICENSE`](LICENSE).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). This project is AI-maintained; human PRs and review are welcome.
