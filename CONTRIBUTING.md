# Contributing to Solana Rug Guard

Thank you for helping make Solana Rug Guard better! Here's how to contribute.

## New Rug Heuristics

The most valuable contributions are new detection checks. Each check should be:

1. **Deterministic** — Same input always produces same output
2. **On-chain first** — No paid APIs, no web scraping
3. **Stdlib-only** — Add to the `rugguard/` package following the existing module layout

### Adding a Check

The engine is split across the `rugguard/` package: `onchain.py` (RPC fetchers + on-chain checks), `scoring.py` (`RugFlags`, scoring), `analysis.py` (the `rug_check_token()` pipeline), `formatting.py`, `cli.py`, `watch.py`.

1. Add your analysis function (e.g., `check_my_risk()`) to `rugguard/onchain.py` or `rugguard/scoring.py`
2. Add any new flags to the `RugFlags` dataclass in `rugguard/scoring.py`
3. Add risk points to `compute_score_components()` in `rugguard/scoring.py`
4. Add to the `rug_check_token()` pipeline in `rugguard/analysis.py`
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
ruff check rugguard/ scripts/ tests/
```

## Pull Request Process

1. Ensure all existing tests pass
2. Add tests for new functionality
3. Update SKILL.md if adding commands or flags
4. Keep each `rugguard/` module focused and reasonably sized
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
