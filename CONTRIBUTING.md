# Contributing to Solana Rug Guard

Thank you for helping make Solana Rug Guard better! Here's how to contribute.

## New Rug Heuristics

The most valuable contributions are new detection checks. Each check should be:

1. **Deterministic** — Same input always produces same output
2. **On-chain first** — No paid APIs, no web scraping
3. **Self-contained** — Add to `scripts/rugguard.py` in the existing pattern

### Adding a Check

1. Add your analysis function (e.g., `check_my_risk()`)
2. Add any new flags to `RugFlags` dataclass
3. Add risk points to `compute_score_components()`
4. Add to the `rug_check_token()` pipeline
5. Add test cases in `tests/test_checks.py`
6. Update the score breakdown table in SKILL.md

## Development Setup

```bash
git clone https://github.com/NousResearch/hermes-agent
cd hermes-agent/optional-skills/blockchain/solana-rug

# Optional: install dev dependencies
pip install pytest ruff mypy

# Run tests
pytest -v

# Lint
ruff check scripts/rugguard.py
```

## Pull Request Process

1. Ensure all existing tests pass
2. Add tests for new functionality
3. Update SKILL.md if adding commands or flags
4. Keep `rugguard.py` under 700 LOC
5. Reference real mainnet addresses in tests

## Code Style

- Python 3.11+ (with `from __future__ import annotations`)
- 100 char line length
- stdlib-first: prefer `urllib` over `httpx` (keep deps optional)
- Data classes for models, not dicts
- Cache every RPC call with 5-min TTL

## Testing Philosophy

Tests use **real mainnet data** via public RPCs. This means:
- Tests hit the live blockchain — no mocking
- Established tokens (BONK, USDC, JUP) have stable, known results
- Tests may fail if the RPC is down
- Rate limits: keep test runs under 15 RPC calls

## License

By contributing, you agree that your contributions will be licensed under MIT.
