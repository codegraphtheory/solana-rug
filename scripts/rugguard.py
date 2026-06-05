#!/usr/bin/env python3
"""rugguard.py — legacy standalone CLI launcher and import shim.

This keeps the documented single-file entrypoint working after the implementation
moved into the ``rugguard`` package. It also preserves the historical test/import
pattern where ``scripts/`` is placed on ``sys.path`` and ``import rugguard`` is
expected to expose the public API.
"""

from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PACKAGE_DIR = os.path.join(_REPO_ROOT, "rugguard")

if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# If this file is imported as module ``rugguard`` from scripts/, make it behave
# like a package so ``rugguard.cli`` and sibling submodules remain importable.
if __name__ == "rugguard":
    __path__ = [_PACKAGE_DIR]  # type: ignore[name-defined]

from rugguard.analysis import RugReport, rug_check_token, rug_check_wallet  # noqa: E402
from rugguard.cli import main  # noqa: E402
from rugguard.formatting import (  # noqa: E402
    _format_comparison_table,
    _format_timeline,
    _format_timeline_json,
    _report_csv_rows,
    _sparkline_from_change,
    _svg_badge,
    _wallet_csv_rows,
    format_csv,
    format_json,
    format_jsonl,
    format_markdown,
)
from rugguard.onchain import (  # noqa: E402
    HolderInfo,
    HoneypotResult,
    LiquidityInfo,
    MintHistory,
    TokenMeta,
    estimate_token_age,
    fetch_token_holders,
    fetch_token_meta,
)
from rugguard.scoring import (  # noqa: E402
    RugFlags,
    RugScore,
    check_authorities,
    compute_safety_score,
    compute_score_components,
)
from rugguard.watch import (  # noqa: E402
    cli_watch,
    describe_watch_change,
    ensure_history_db,
    load_last_history,
    prune_history,
    record_history,
    send_webhook,
)

__all__ = [
    "rug_check_token",
    "rug_check_wallet",
    "format_markdown",
    "format_json",
    "format_csv",
    "format_jsonl",
    "_format_comparison_table",
    "_format_timeline",
    "_format_timeline_json",
    "_report_csv_rows",
    "_sparkline_from_change",
    "_svg_badge",
    "_wallet_csv_rows",
    "RugReport",
    "RugScore",
    "RugFlags",
    "TokenMeta",
    "LiquidityInfo",
    "HolderInfo",
    "HoneypotResult",
    "MintHistory",
    "estimate_token_age",
    "fetch_token_meta",
    "fetch_token_holders",
    "check_authorities",
    "compute_safety_score",
    "compute_score_components",
    "cli_watch",
    "ensure_history_db",
    "load_last_history",
    "record_history",
    "prune_history",
    "describe_watch_change",
    "send_webhook",
]


if __name__ == "__main__":
    main()
