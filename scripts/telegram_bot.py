#!/usr/bin/env python3
"""telegram_bot.py — Telegram bot for Solana Rug Guard.

Provides /check and /watch commands for Solana token safety checks.
Shares SQLite watch database with CLI watch mode.

Usage:
    TELEGRAM_BOT_TOKEN=xxx python telegram_bot.py

Dependencies (optional):
    pip install python-telegram-bot
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

# Add scripts to path so we can import rugguard
_scripts = str(Path(__file__).resolve().parent)
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import rugguard  # noqa: E402

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("solana-rug-bot")

# ── Configuration ──────────────────────────────────────────────────────────

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
if not TOKEN:
    print("Error: TELEGRAM_BOT_TOKEN env var is required", file=sys.stderr)
    sys.exit(1)

WATCH_DB = os.environ.get(
    "SOLANA_RUG_HISTORY",
    str(Path.home() / ".solana-rug" / "history.sqlite3"),
)

# Rate limiting: max 1 request per 5 seconds per user
RATE_LIMIT_SECONDS = 5
_last_request: dict[int, float] = {}

# ── Database ───────────────────────────────────────────────────────────────

def _ensure_db() -> sqlite3.Connection:
    """Open or create the watch database, ensuring the telegram_watches table exists."""
    Path(WATCH_DB).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(WATCH_DB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS telegram_watches (
            chat_id INTEGER NOT NULL,
            mint TEXT NOT NULL,
            last_score REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL DEFAULT (julianday('now')),
            PRIMARY KEY (chat_id, mint)
        )
    """)
    conn.commit()
    return conn


def _add_watch(chat_id: int, mint: str) -> None:
    conn = _ensure_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO telegram_watches (chat_id, mint) VALUES (?, ?)",
            (chat_id, mint),
        )
        conn.commit()
    finally:
        conn.close()


def _remove_watch(chat_id: int, mint: str) -> None:
    conn = _ensure_db()
    try:
        conn.execute(
            "DELETE FROM telegram_watches WHERE chat_id = ? AND mint = ?",
            (chat_id, mint),
        )
        conn.commit()
    finally:
        conn.close()


def _get_watches(chat_id: int | None = None) -> list[dict[str, Any]]:
    conn = _ensure_db()
    try:
        if chat_id:
            rows = conn.execute(
                "SELECT chat_id, mint, last_score FROM telegram_watches WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT chat_id, mint, last_score FROM telegram_watches",
            ).fetchall()
        return [
            {"chat_id": r[0], "mint": r[1], "last_score": r[2]} for r in rows
        ]
    finally:
        conn.close()


def _update_score(chat_id: int, mint: str, score: float) -> None:
    conn = _ensure_db()
    try:
        conn.execute(
            "UPDATE telegram_watches SET last_score = ? WHERE chat_id = ? AND mint = ?",
            (score, chat_id, mint),
        )
        conn.commit()
    finally:
        conn.close()


# ── Rate Limiter ───────────────────────────────────────────────────────────

def _check_rate_limit(chat_id: int) -> bool:
    """Return True if request is allowed, False if rate-limited."""
    now = time.time()
    last = _last_request.get(chat_id, 0)
    if now - last < RATE_LIMIT_SECONDS:
        return False
    _last_request[chat_id] = now
    return True


# ── Report Formatting ──────────────────────────────────────────────────────

def _format_report(mint: str) -> str:
    """Generate a compact safety report for Telegram (under 4096 chars)."""
    try:
        report = rugguard.rug_check_token(mint.strip())
    except Exception as e:
        return f"Error checking {mint[:8]}...: {str(e)[:200]}"

    symbol = report.token.symbol or report.token.name or f"{mint[:4]}...{mint[-4:]}"
    lines = [
        f"*🛡️ {symbol} Safety Report*",
        "",
        f"**Score:** {report.safety_score}/100 — **{report.risk_level}**",
        f"**Mint:** `{mint}`",
        "",
    ]

    # Score breakdown
    s = report.score
    lines.append("*Score Factors:*")
    items = [
        ("Mint", s.mint_authority_risk),
        ("Freeze", s.freeze_authority_risk),
        ("Liquidity", s.liquidity_risk),
        ("Holders", s.holder_concentration_risk),
        ("Age", s.age_risk),
        ("Honeypot", s.honeypot_risk),
        ("Sniper", s.sniper_risk),
        ("Name", s.name_risk),
    ]
    for name, val in items:
        icon = "✅" if val == 0 else "⚠️" if val < 5 else "🔴"
        lines.append(f"  {icon} {name}: {val}/10")

    # Warnings
    if report.warnings:
        lines.append("")
        lines.append("*Warnings:*")
        for w in report.warnings[:5]:
            lines.append(f"  ⚠️ {w[:120]}")

    # Market data
    if report.dex_data:
        dd = report.dex_data
        lines.append("")
        lines.append("*Market:*")
        if dd.get("price_usd"):
            p = dd["price_usd"]
            lines.append(f"  Price: ${p:.8f}" if p < 1 else f"  Price: ${p:.4f}")
        if dd.get("price_change_24h"):
            pct = dd["price_change_24h"]
            arrow = "📈" if pct > 0 else "📉"
            lines.append(f"  24h: {arrow} {pct:+.2f}%")
        if dd.get("liquidity_usd"):
            lines.append(f"  Liq: ${dd['liquidity_usd']:,.0f}")

    lines.append("")
    lines.append(report.recommendation[:200])
    return "\n".join(lines)


# ── Bot Handlers ───────────────────────────────────────────────────────────

def _start_handler(update: Any, context: Any) -> None:
    """Handle /start command."""
    update.message.reply_text(
        "🤖 *Solana Rug Guard Bot*\n\n"
        "I check Solana tokens for rug-pull risks.\n\n"
        "*/check <MINT>* — Get safety report\n"
        "*/watch <MINT>* — Start monitoring\n"
        "*/unwatch <MINT>* — Stop monitoring\n"
        "*/watches* — List your watched tokens\n"
        "*/help* — This message\n\n"
        "Get a bot token from @Botfather and set TELEGRAM_BOT_TOKEN.",
        parse_mode="Markdown",
    )


def _check_handler(update: Any, context: Any) -> None:
    """Handle /check command."""
    chat_id = update.effective_user.id
    if not _check_rate_limit(chat_id):
        update.message.reply_text("⏳ Please wait a few seconds between checks.")
        return

    args = context.args
    if not args:
        update.message.reply_text("Usage: /check <MINT_ADDRESS>")
        return

    mint = args[0]
    msg = update.message.reply_text("🔍 Checking token...")
    report = _format_report(mint)
    try:
        msg.edit_text(report, parse_mode="Markdown")
    except Exception:
        # Fallback if markdown formatting fails
        msg.edit_text(report.replace("*", "").replace("_", ""))


def _watch_handler(update: Any, context: Any) -> None:
    """Handle /watch command."""
    chat_id = update.effective_user.id
    args = context.args
    if not args:
        update.message.reply_text("Usage: /watch <MINT_ADDRESS>")
        return

    mint = args[0]
    _add_watch(chat_id, mint)

    # Get initial score
    try:
        report = rugguard.rug_check_token(mint.strip())
        _update_score(chat_id, mint, report.safety_score)
    except Exception:
        pass

    update.message.reply_text(
        f"✅ Watching `{mint[:8]}...`\n"
        f"I'll alert you if the score drops significantly.",
        parse_mode="Markdown",
    )


def _unwatch_handler(update: Any, context: Any) -> None:
    """Handle /unwatch command."""
    chat_id = update.effective_user.id
    args = context.args
    if not args:
        update.message.reply_text("Usage: /unwatch <MINT_ADDRESS>")
        return

    mint = args[0]
    _remove_watch(chat_id, mint)
    update.message.reply_text(f"Stopped watching `{mint[:8]}...`", parse_mode="Markdown")


def _watches_handler(update: Any, context: Any) -> None:
    """Handle /watches command."""
    chat_id = update.effective_user.id
    watches = _get_watches(chat_id)
    if not watches:
        update.message.reply_text("No watched tokens. Use /watch <MINT> to add one.")
        return

    lines = ["*Your watched tokens:*"]
    for w in watches:
        lines.append(f"  `{w['mint'][:8]}...` — Score: {w['last_score']:.0f}")
    update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Alert Checker ─────────────────────────────────────────────────────────

def check_alerts(bot: Any) -> None:
    """Check all watched tokens for score drops > 10 points."""
    watches = _get_watches()
    for w in watches:
        try:
            report = rugguard.rug_check_token(w["mint"])
        except Exception:
            continue

        new_score = report.safety_score
        old_score = w["last_score"]
        drop = old_score - new_score

        if drop >= 10:
            _update_score(w["chat_id"], w["mint"], new_score)
            symbol = report.token.symbol or w["mint"][:8]
            try:
                bot.send_message(
                    chat_id=w["chat_id"],
                    text=(
                        f"⚠️ *{symbol} Alert!*\n"
                        f"Score dropped: {old_score:.0f} \u2192 {new_score:.0f} ({drop:.0f} pts)\n"
                        f"Risk: *{report.risk_level}*\n"
                        f"Warnings: {len(report.warnings)}\n"
                        f"Use /check `{w['mint'][:8]}...` for full report."
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        elif abs(new_score - old_score) >= 3:
            # Minor update — just persist the new score
            _update_score(w["chat_id"], w["mint"], new_score)


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    from telegram.ext import CommandHandler, Updater

    updater = Updater(token=TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", _start_handler))
    dp.add_handler(CommandHandler("help", _start_handler))
    dp.add_handler(CommandHandler("check", _check_handler))
    dp.add_handler(CommandHandler("watch", _watch_handler))
    dp.add_handler(CommandHandler("unwatch", _unwatch_handler))
    dp.add_handler(CommandHandler("watches", _watches_handler))

    # Start periodic alert checking (every 5 minutes)
    import threading

    def _alert_loop():
        while True:
            time.sleep(300)
            try:
                check_alerts(updater.bot)
            except Exception as e:
                logger.error("Alert check failed: %s", e)

    thread = threading.Thread(target=_alert_loop, daemon=True)
    thread.start()

    logger.info("Bot started. Press Ctrl+C to stop.")
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()
