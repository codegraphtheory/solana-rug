#!/usr/bin/env python3
"""rugguard/watch.py -- Watch mode for Solana Rug Guard: continuous monitoring
with history tracking and webhook alerts.

Extracted from scripts/rugguard.py.

MIT License -- free, open-source, no paid APIs required.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request

from .analysis import RugReport

DEFAULT_HISTORY_DB = os.environ.get(
    "SOLANA_RUG_HISTORY_DB",
    os.path.expanduser("~/.solana-rug/history.sqlite3"),
)
HISTORY_RETENTION_DAYS = int(os.environ.get("SOLANA_RUG_HISTORY_RETENTION_DAYS", "90"))
WEBHOOK_COOLDOWN_SECONDS = 3600  # at most 1 alert per token per hour
_last_webhook_alert: dict[str, float] = {}  # mint -> timestamp of last alert


def _risk_signature(report: RugReport) -> dict:
    """Return stable fields used to decide whether a watched token changed."""
    warning_list = report.warnings or report.flags.flagged_warnings or []
    return {
        "safety_score": report.safety_score,
        "risk_level": report.risk_level,
        "warnings": sorted(set(warning_list)),
        "flags": {k: v for k, v in report.to_dict().get("flags", {}).items() if v is True},
    }


def ensure_history_db(path: str = DEFAULT_HISTORY_DB) -> str:
    """Create the SQLite history database if needed and return its path."""
    db_path = os.path.expanduser(path)
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mint TEXT NOT NULL,
                checked_at INTEGER NOT NULL,
                safety_score INTEGER NOT NULL,
                risk_level TEXT NOT NULL,
                warning_count INTEGER NOT NULL,
                signature_json TEXT NOT NULL,
                report_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_scores_mint_time "
            "ON token_scores(mint, checked_at)"
        )
    prune_history(db_path)
    return db_path


def prune_history(path: str = DEFAULT_HISTORY_DB) -> int:
    """Delete token_score rows older than HISTORY_RETENTION_DAYS.
    Returns count of deleted rows.
    """
    cutoff = int(time.time()) - HISTORY_RETENTION_DAYS * 86400
    with sqlite3.connect(os.path.expanduser(path)) as conn:
        cursor = conn.execute("DELETE FROM token_scores WHERE checked_at < ?", (cutoff,))
        return cursor.rowcount


def load_last_history(mint: str, path: str = DEFAULT_HISTORY_DB) -> dict | None:
    """Load the most recent saved signature for a mint."""
    db_path = ensure_history_db(path)
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT checked_at, safety_score, risk_level, signature_json
            FROM token_scores
            WHERE mint = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT 1
            """,
            (mint,),
        ).fetchone()
    if not row:
        return None
    return {
        "checked_at": row[0],
        "safety_score": row[1],
        "risk_level": row[2],
        "signature": json.loads(row[3]),
    }


def record_history(report: RugReport, path: str = DEFAULT_HISTORY_DB) -> str:
    """Persist a token report into SQLite history."""
    db_path = ensure_history_db(path)
    signature = _risk_signature(report)
    report_json = json.dumps(report.to_dict(), sort_keys=True, default=str)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO token_scores (
                mint, checked_at, safety_score, risk_level,
                warning_count, signature_json, report_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.token.address,
                int(time.time()),
                report.safety_score,
                report.risk_level,
                len(signature["warnings"]),
                json.dumps(signature, sort_keys=True),
                report_json,
            ),
        )
    return db_path


def describe_watch_change(
    previous: dict | None,
    report: RugReport,
    threshold: int | None = None,
) -> tuple[bool, list[str]]:
    """Compare current report to previous history and return alert reasons."""
    reasons: list[str] = []
    current = _risk_signature(report)
    if threshold is not None and report.safety_score <= threshold:
        reasons.append(f"safety score {report.safety_score} <= threshold {threshold}")
    if previous is None:
        reasons.append("first observation")
    else:
        prev = previous.get("signature", {})
        if current.get("safety_score") != prev.get("safety_score"):
            reasons.append(
                f"score changed {prev.get('safety_score')} -> "
                f"{current.get('safety_score')}"
            )
        if current.get("risk_level") != prev.get("risk_level"):
            reasons.append(
                f"risk level changed {prev.get('risk_level')} -> "
                f"{current.get('risk_level')}"
            )
        if current.get("flags") != prev.get("flags"):
            reasons.append("risk flags changed")
        if current.get("warnings") != prev.get("warnings"):
            reasons.append("warnings changed")
    return bool(reasons), reasons


def send_webhook(url: str, payload: dict, timeout: int = 8) -> bool:
    """POST a JSON alert payload to a webhook URL."""
    if not url.startswith("https://"):
        raise ValueError(f"webhook URL must use https://, got: {url[:30]}...")
    data = json.dumps(payload, default=str).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "solana-rug/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return 200 <= resp.status < 300


def _parse_watch_args(args: list[str]) -> dict:
    mint = args[0] if args else ""
    if not mint:
        usage = (
            "Usage: python rugguard.py watch <MINT_ADDRESS> [--interval 60] "
            "[--iterations 0] [--history PATH] [--webhook URL] [--threshold SCORE]"
        )
        print(usage, file=sys.stderr)
        sys.exit(1)
    opts = {
        "mint": mint.strip(),
        "interval": int(os.environ.get("SOLANA_RUG_WATCH_INTERVAL", "60")),
        "iterations": 0,
        "history": DEFAULT_HISTORY_DB,
        "webhook": os.environ.get("SOLANA_RUG_WEBHOOK_URL", ""),
        "threshold": None,
    }
    i = 1
    while i < len(args):
        arg = args[i]
        if arg == "--interval" and i + 1 < len(args):
            opts["interval"] = max(1, int(args[i + 1]))
            i += 2
        elif arg == "--iterations" and i + 1 < len(args):
            opts["iterations"] = max(0, int(args[i + 1]))
            i += 2
        elif arg == "--history" and i + 1 < len(args):
            opts["history"] = args[i + 1]
            i += 2
        elif arg == "--webhook" and i + 1 < len(args):
            opts["webhook"] = args[i + 1]
            i += 2
        elif arg == "--threshold" and i + 1 < len(args):
            opts["threshold"] = int(args[i + 1])
            i += 2
        else:
            print(f"Unknown watch option: {arg}", file=sys.stderr)
            sys.exit(1)
    return opts


def cli_watch(args: list[str]) -> None:
    opts = _parse_watch_args(args)
    mint = opts["mint"]
    from .analysis import rug_check_token  # noqa: F811

    iteration = 0
    while True:
        previous = load_last_history(mint, opts["history"])
        report = rug_check_token(mint)
        changed, reasons = describe_watch_change(previous, report, opts["threshold"])
        db_path = record_history(report, opts["history"])
        event = {
            "mint": mint,
            "checked_at": int(time.time()),
            "safety_score": report.safety_score,
            "risk_level": report.risk_level,
            "changed": changed,
            "reasons": reasons,
            "history_db": db_path,
            "warnings": report.warnings,
        }
        if opts["webhook"] and changed:
            now = time.time()
            last_alert = WEBHOOK_COOLDOWN_SECONDS  # default: allow if never alerted
            if mint in _last_webhook_alert:
                last_alert = now - _last_webhook_alert[mint]
            if last_alert >= WEBHOOK_COOLDOWN_SECONDS:
                try:
                    event["webhook_sent"] = send_webhook(opts["webhook"], event)
                    _last_webhook_alert[mint] = now
                except Exception as exc:
                    event["webhook_sent"] = False
                    event["webhook_error"] = str(exc)
            else:
                cooldown_remaining = int(WEBHOOK_COOLDOWN_SECONDS - last_alert)
                event["webhook_cooldown"] = cooldown_remaining
        print(json.dumps(event, indent=2, default=str), flush=True)
        iteration += 1
        if opts["iterations"] and iteration >= opts["iterations"]:
            break
        time.sleep(opts["interval"])
