# Contributing

## Maintainer disclosure

**agent-cost-logger** is created and maintained by **Moneymaker**, an AI agent working for **Ray Malhotra**. Issues and pull requests from humans are welcome and appreciated. Expect AI-authored responses and merges; Ray may review sensitive changes.

## How to help

1. Open an issue describing the bug or enhancement (include sample JSONL if relevant).
2. Keep PRs focused — one behavior change per PR when possible.
3. Do not commit secrets, real API keys, or personal spend logs.
4. Prefer stdlib-only changes unless there is a strong reason to add a dependency.
5. Update README examples if CLI flags change.

## Local check

```bash
python3 cost_logger.py --help
python3 cost_logger.py summarize --file example_data.jsonl --by-model
```

## Code of conduct (short)

Be kind. No spam, no abuse, no drive-by marketing in issues. Disclose AI assistance if you use it in your PR description.
