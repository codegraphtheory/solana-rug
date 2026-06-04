#!/usr/bin/env python3
"""rugguard/cli.py -- CLI dispatch for Solana Rug Guard.

Extracted from scripts/rugguard.py.

MIT License -- free, open-source, no paid APIs required.
"""

from __future__ import annotations

import json
import sys

from .analysis import RugReport, rug_check_token, rug_check_wallet
from .formatting import (
    _fetch_timeline_events,
    _format_comparison_table,
    _format_timeline,
    _format_timeline_json,
    _report_csv_rows,
    _svg_badge,
    _wallet_csv_rows,
    format_csv,
    format_json,
    format_jsonl,
    format_markdown,
)
from .onchain import TokenMeta
from .scoring import RugFlags, RugScore
from .watch import cli_watch


def cli_token(args: list[str]) -> None:
    mint = args[0] if args else ""
    if not mint:
        print(
            "Usage: python rugguard.py token <MINT_ADDRESS> "
            "[--json|--markdown|--export csv|jsonl]",
            file=sys.stderr,
        )
        sys.stderr.write("\n")
        sys.exit(1)

    mode = "json"
    export_fmt = None
    if "--json" in args:
        mode = "json"
    if "--markdown" in args or "--md" in args:
        mode = "markdown"
    # Handle --export csv, --export=jsonl, etc.
    for a in args:
        if a == "--export":
            idx = args.index("--export")
            if idx + 1 < len(args):
                export_fmt = args[idx + 1].lower()
            else:
                print("--export requires a value: csv or jsonl", file=sys.stderr)
                sys.exit(1)
            mode = "export"
            break
        elif a.startswith("--export="):
            export_fmt = a.split("=", 1)[1].lower()
            if export_fmt not in ("csv", "jsonl"):
                print(
                    f"Unknown --export format: {export_fmt} (use csv or jsonl)",
                    file=sys.stderr,
                )
                sys.exit(1)
            mode = "export"
            break

    report = rug_check_token(mint.strip())
    if mode == "export":
        rows = _report_csv_rows(report)
        if export_fmt == "csv":
            print(format_csv(rows))
        elif export_fmt == "jsonl":
            print(format_jsonl(rows))
        else:
            print(
                f"Unknown --export format: {export_fmt} (use csv or jsonl)",
                file=sys.stderr,
            )
            sys.exit(1)
    elif mode == "markdown":
        print(format_markdown(report))
    else:
        print(format_json(report))

    if report.safety_score < 40:
        sys.exit(2)


def cli_wallet(args: list[str]) -> None:
    address = args[0] if args else ""
    if not address:
        print(
            "Usage: python rugguard.py wallet <ADDRESS> [--export csv|jsonl]",
            file=sys.stderr,
        )
        sys.exit(1)

    export_fmt = None
    for a in args:
        if a == "--export":
            idx = args.index("--export")
            if idx + 1 < len(args):
                export_fmt = args[idx + 1].lower()
            else:
                print("--export requires a value: csv or jsonl", file=sys.stderr)
                sys.exit(1)
            break
        elif a.startswith("--export="):
            export_fmt = a.split("=", 1)[1].lower()
            if export_fmt not in ("csv", "jsonl"):
                print(
                    f"Unknown --export format: {export_fmt} (use csv or jsonl)",
                    file=sys.stderr,
                )
                sys.exit(1)
            break

    disable_progress = "--json" in args or "--export" in args
    result = rug_check_wallet(address.strip(), disable_progress=disable_progress)
    if export_fmt == "csv":
        rows = _wallet_csv_rows(result)
        print(format_csv(rows))
    elif export_fmt == "jsonl":
        rows = _wallet_csv_rows(result)
        print(format_jsonl(rows))
    else:
        print(json.dumps(result, indent=2, default=str))

    if result.get("risky_count", 0) > 0:
        sys.exit(2)


def cli_badge(args: list[str]) -> None:
    """Generate an SVG safety score badge for a token."""
    if not args:
        print(
            "Usage: python rugguard.py badge <MINT> [--style flat|flat-square|plastic] "
            "[--label TEXT]",
            file=sys.stderr,
        )
        sys.exit(1)

    mint = args[0]
    style = "flat"
    label = "safety"

    for idx, a in enumerate(args):
        if a.startswith("--style="):
            style = a.split("=", 1)[1]
        elif a == "--style" and idx + 1 < len(args):
            style = args[idx + 1]
        if a.startswith("--label="):
            label = a.split("=", 1)[1]
        elif a == "--label" and idx + 1 < len(args):
            label = args[idx + 1]

    report = rug_check_token(mint.strip())
    print(_svg_badge(report, style=style, label=label))


def cli_compare(args: list[str]) -> None:
    """Compare multiple tokens side-by-side."""
    if not args:
        print(
            "Usage: python rugguard.py compare "
            "<MINT1> <MINT2> [<MINT3> ...]",
            file=sys.stderr,
        )
        sys.exit(1)

    # Parse flags
    as_json = "--json" in args
    sort_by = "score"
    mints = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--json":
            i += 1
            continue
        if a == "--sort" and i + 1 < len(args):
            sort_by = args[i + 1]
            i += 2
            continue
        if a.startswith("--sort="):
            sort_by = a.split("=", 1)[1]
            i += 1
            continue
        mints.append(a)
        i += 1

    if len(mints) < 2:
        print("Error: need at least 2 mint addresses to compare", file=sys.stderr)
        sys.exit(1)

    reports: list[RugReport] = []
    errors: list[str] = []

    for mint in mints:
        try:
            report = rug_check_token(mint.strip())
            reports.append(report)
        except Exception as e:
            errors.append(f"{mint[:8]}...: {e}")
            # Insert a minimal placeholder for failed token
            reports.append(
                RugReport(
                    token=TokenMeta(address=mint),
                    safety_score=0,
                    risk_level="ERROR",
                    score=RugScore(),
                    flags=RugFlags(),
                    warnings=[],
                    recommendation="Check failed",
                )
            )

    if errors:
        for e in errors:
            print(f"Warning: {e}", file=sys.stderr)

    if as_json:
        print(json.dumps([r.to_dict() for r in reports], indent=2, default=str))
    else:
        print(_format_comparison_table(reports, sort_by=sort_by))


def cli_timeline(args: list[str]) -> None:
    """Show token timeline events."""
    if not args:
        print(
            "Usage: python rugguard.py timeline <MINT> [--json]",
            file=sys.stderr,
        )
        sys.exit(1)

    mint = args[0]
    as_json = "--json" in args[1:]

    events = _fetch_timeline_events(mint.strip())
    if as_json:
        print(_format_timeline_json(events))
    else:
        print(_format_timeline(mint, events))


def cli_help() -> None:
    print(
        """Solana Rug Guard -- On-chain rug-pull detection engine

USAGE:
    python rugguard.py token <MINT_ADDRESS> [--json|--markdown]
    python rugguard.py wallet <WALLET_ADDRESS>
    python rugguard.py badge <MINT> [--style flat|flat-square|plastic] [--label TEXT]
    python rugguard.py compare <MINT1> <MINT2> [<MINT3> ...] [--json]
    python rugguard.py timeline <MINT> [--json]
    python rugguard.py watch <MINT_ADDRESS> [--interval 60] [--iterations 0]
        [--history PATH] [--webhook URL] [--threshold SCORE]

OPTIONS:
    --json        Output as JSON (default for token)
    --markdown    Output as Markdown report
    --md          Alias for --markdown
    --export csv  Export as CSV (compatible with spreadsheets)
    --export jsonl
                  Export as JSONL (one JSON object per line)
    --sort        Sort tokens in compare output (default: score)

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
    python rugguard.py wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM --export jsonl
    python rugguard.py badge DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
    python rugguard.py compare DezXAZ8z... EPjFWdd5... [--json]
    python rugguard.py timeline DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
    python rugguard.py watch <MINT_ADDRESS> --iterations 1 --threshold 70

ENVIRONMENT:
    SOLANA_RPC_URL    Override RPC endpoint (default: api.mainnet-beta.solana.com)

EXIT CODES:
    0    No critical risks detected
    2    High/critical risk detected"""
    )


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        cli_help()
        sys.exit(0)

    cmd = sys.argv[1]
    args_list = sys.argv[2:]

    if cmd == "token":
        cli_token(args_list)
    elif cmd == "wallet":
        cli_wallet(args_list)
    elif cmd == "badge":
        cli_badge(args_list)
    elif cmd == "compare":
        cli_compare(args_list)
    elif cmd == "timeline":
        cli_timeline(args_list)
    elif cmd == "watch":
        cli_watch(args_list)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        cli_help()
        sys.exit(1)
