"""solana_rug — On-chain rug-pull detection for Solana tokens.

This package wraps the core rugguard.py engine as a pip-installable module.

Usage:
    from solana_rug import rug_check_token, RugReport
    report = rug_check_token("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263")
    print(report.safety_score)
"""

# Re-export the core engine from rugguard.py
import os
import sys
from importlib.metadata import version as _version

# Add scripts directory to path so we can import rugguard
_scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from rugguard import (  # noqa: E402
    HolderInfo,
    HoneypotResult,
    LiquidityInfo,
    MintHistory,
    RugFlags,
    RugReport,
    RugScore,
    TokenMeta,
    format_json,
    format_markdown,
    rug_check_token,
    rug_check_wallet,
)

try:
    __version__ = _version("solana-rug")
except Exception:
    __version__ = "0.1.0"

__all__ = [
    "rug_check_token",
    "rug_check_wallet",
    "format_markdown",
    "format_json",
    "RugReport",
    "RugScore",
    "RugFlags",
    "TokenMeta",
    "LiquidityInfo",
    "HolderInfo",
    "HoneypotResult",
    "MintHistory",
]
