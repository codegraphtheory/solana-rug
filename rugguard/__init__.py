"""rugguard — On-chain rug-pull detection for Solana tokens.

The core engine: RPC access, on-chain fetchers, risk scoring, and reporting.

Usage:
    from rugguard import rug_check_token, RugReport
    report = rug_check_token("DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263")
    print(report.safety_score)
"""

from importlib.metadata import version as _version

from .analysis import RugReport, rug_check_token, rug_check_wallet
from .formatting import format_json, format_markdown
from .onchain import (
    HolderInfo,
    HoneypotResult,
    LiquidityInfo,
    MintHistory,
    TokenMeta,
)
from .scoring import RugFlags, RugScore

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
