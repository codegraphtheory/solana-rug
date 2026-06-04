from __future__ import annotations

import json
import sys

from .analysis import rug_check_token, rug_check_wallet
from .formatting import format_json, format_markdown
from .watch import cli_watch


def cli_token(args: list[str]) -> None:
    mint = args[0] if args else ""
    if not mint:
        print("Usage: python rugguard.py token <MINT_ADDRESS>", file=sys.stderr)
        sys.exit(1)

    mode = "json"
    if "--json" in args:
        mode = "json"
    if "--markdown" in args or "--md" in args:
        mode = "markdown"

    report = rug_check_token(mint.strip())
    if mode == "markdown":
        print(format_markdown(report))
    else:
        print(format_json(report))

    if report.safety_score < 40:
        sys.exit(2)


def cli_wallet(args: list[str]) -> None:
    address = args[0] if args else ""
    if not address:
        print("Usage: python rugguard.py wallet <ADDRESS>", file=sys.stderr)
        sys.exit(1)

    result = rug_check_wallet(address.strip())
    print(json.dumps(result, indent=2, default=str))

    if result.get("risky_count", 0) > 0:
        sys.exit(2)


def cli_help() -> None:
    print("""Solana Rug Guard — On-chain rug-pull detection engine

USAGE:
    python rugguard.py token <MINT_ADDRESS> [--json|--markdown]
    python rugguard.py wallet <WALLET_ADDRESS>
    python rugguard.py watch <MINT_ADDRESS> [--interval 60] [--iterations 0]
        [--history PATH] [--webhook URL] [--threshold SCORE]

OPTIONS:
    --json        Output as JSON (default for token)
    --markdown    Output as Markdown report
    --md          Alias for --markdown

WATCH OPTIONS:
    --interval    Seconds between checks (default: 60)
    --iterations  Number of checks before exit; 0 means forever (default: 0)
    --history     SQLite history path (default: ~/.solana-rug/history.sqlite3)
    --webhook     POST JSON alerts to this URL when score/flags/warnings change
    --threshold   Alert whenever safety_score is <= this value

EXAMPLES:
    python rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
    python rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --markdown
    python rugguard.py wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM
    python rugguard.py watch <MINT_ADDRESS> --iterations 1 --threshold 70

ENVIRONMENT:
    SOLANA_RPC_URL    Override RPC endpoint (default: api.mainnet-beta.solana.com)

EXIT CODES:
    0    No critical risks detected
    2    High/critical risk detected""")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        cli_help()
        sys.exit(0)

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "token":
        cli_token(args)
    elif cmd == "wallet":
        cli_wallet(args)
    elif cmd == "watch":
        cli_watch(args)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        cli_help()
        sys.exit(1)
