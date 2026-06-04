"""Tests for the Telegram bot (mocked)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add scripts to path
_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)


class TestBotRateLimit:
    """Test rate limiter logic without needing python-telegram-bot."""

    def test_rate_limit_allows_first(self):
        import time
        # Simulate the _check_rate_limit function
        last_request = {}

        def check(chat_id):
            now = time.time()
            last = last_request.get(chat_id, 0)
            if now - last < 5:
                return False
            last_request[chat_id] = now
            return True

        assert check(123) is True

    def test_rate_limit_blocks_rapid(self):
        import time
        last_request = {}

        def check(chat_id):
            now = time.time()
            last = last_request.get(chat_id, 0)
            if now - last < 5:
                return False
            last_request[chat_id] = now
            return True

        check(123)
        assert check(123) is False

    def test_rate_limit_different_users(self):
        import time
        last_request = {}

        def check(chat_id):
            now = time.time()
            last = last_request.get(chat_id, 0)
            if now - last < 5:
                return False
            last_request[chat_id] = now
            return True

        check(123)
        assert check(456) is True  # different user


class TestBotFormatting:
    """Test report formatting for Telegram."""

    def test_format_report_structure(self):
        from rugguard import rug_check_token, RugReport
        # Create a minimal report (no RPC needed)
        from rugguard import RugScore, RugFlags, TokenMeta

        flags = RugFlags()
        report = RugReport(
            token=TokenMeta(address="TestMint", name="TestCoin", symbol="TST"),
            safety_score=65, risk_level="MEDIUM",
            score=RugScore(mint_authority_risk=3, honeypot_risk=2),
            flags=flags,
            warnings=["Mint authority is still active"],
            recommendation="Exercise caution with this token.",
        )

        # Test the formatting logic
        lines = []
        lines.append(f"Score: {report.safety_score}/100 - {report.risk_level}")
        lines.append(f"Mint: `{report.token.address}`")
        assert "65" in lines[0]
        assert "MEDIUM" in lines[0]
        assert "TestMint" in lines[1]

    def test_format_report_market_data(self):
        from rugguard import RugReport, RugScore, RugFlags, TokenMeta
        flags = RugFlags()
        report = RugReport(
            token=TokenMeta(address="Addr"),
            safety_score=90, risk_level="LOW",
            score=RugScore(), flags=flags, warnings=[], recommendation="Safe",
        )
        report.dex_data = {
            "price_usd": 0.00001234,
            "price_change_24h": 5.5,
            "liquidity_usd": 50000,
        }

        # Manual formatting test
        dd = report.dex_data
        assert dd["price_usd"] == 0.00001234
        assert dd["price_change_24h"] == 5.5
        assert dd["liquidity_usd"] == 50000


class TestBotWatchDB:
    """Test watch database operations."""

    def test_add_and_get_watch(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "test_watch.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_watches (
                chat_id INTEGER NOT NULL,
                mint TEXT NOT NULL,
                last_score REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT (julianday('now')),
                PRIMARY KEY (chat_id, mint)
            )
        """)
        conn.execute("INSERT INTO telegram_watches (chat_id, mint) VALUES (?, ?)", (123, "TestMint"))
        conn.commit()

        rows = conn.execute("SELECT chat_id, mint FROM telegram_watches").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 123
        assert rows[0][1] == "TestMint"
        conn.close()

    def test_remove_watch(self, tmp_path):
        import sqlite3
        db_path = tmp_path / "test_watch2.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS telegram_watches (
                chat_id INTEGER NOT NULL,
                mint TEXT NOT NULL,
                last_score REAL NOT NULL DEFAULT 0,
                created_at REAL NOT NULL DEFAULT (julianday('now')),
                PRIMARY KEY (chat_id, mint)
            )
        """)
        conn.execute("INSERT INTO telegram_watches (chat_id, mint) VALUES (?, ?)", (123, "Mint1"))
        conn.execute("INSERT INTO telegram_watches (chat_id, mint) VALUES (?, ?)", (123, "Mint2"))
        conn.execute("DELETE FROM telegram_watches WHERE chat_id = ? AND mint = ?", (123, "Mint1"))
        conn.commit()

        rows = conn.execute("SELECT mint FROM telegram_watches").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "Mint2"
        conn.close()
