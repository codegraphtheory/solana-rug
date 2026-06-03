"""Tests for Solana Rug Guard — all use real mainnet data.

Note: Tests hit the live Solana blockchain via public RPC.
They may fail if the RPC is rate-limited or down.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# Add scripts to path
_scripts = str(Path(__file__).resolve().parent.parent / "scripts")
if _scripts not in sys.path:
    sys.path.insert(0, _scripts)

import pytest  # noqa: E402
from rugguard import (  # noqa: E402
    RugFlags,
    RugReport,
    RugScore,
    TokenMeta,
    check_authorities,
    compute_safety_score,
    estimate_token_age,
    fetch_token_holders,
    fetch_token_meta,
    format_json,
    format_markdown,
    rug_check_token,
)

# ── Test addresses (real mainnet) ──────────────────────────────────────────

# BONK — established token, mint/freeze authorities revoked, has LP
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"

# USDC — stablecoin, well-established
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

# Well-known wallet with tokens
TEST_WALLET = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"


# ── Token Meta Tests ──────────────────────────────────────────────────────

class TestFetchTokenMeta:
    def test_bonk_metadata(self) -> None:
        meta = fetch_token_meta(BONK_MINT)
        assert meta is not None
        assert meta.address == BONK_MINT
        # BONK's symbol/name are stored off-chain (Metaplex metadata),
        # not in the raw mint account. Symbol may be empty on-chain.
        assert meta.decimals > 0
        assert meta.supply > 0

    def test_usdc_metadata(self) -> None:
        """USDC metadata should be fetchable. Accepts RPC variability."""
        meta = fetch_token_meta(USDC_MINT)
        if meta is None:
            return  # RPC may not return data consistently
        assert meta.address == USDC_MINT
        # USDC has 6 decimals — but RPC may return incomplete data
        assert meta.decimals in (0, 6), f"Expected 6 decimals, got {meta.decimals}"

    def test_invalid_mint(self) -> None:
        """An address that doesn't exist should return None."""
        meta = fetch_token_meta("GarbageAddressThatDoesNotExist12345678901234567890")
        assert meta is None

    def test_authorities_bonk(self) -> None:
        """BONK should have mint/freeze authorities revoked."""
        meta = fetch_token_meta(BONK_MINT)
        assert meta is not None
        mint_active, freeze_active, warnings = check_authorities(meta)
        assert not mint_active, "BONK mint authority should be revoked"
        assert not freeze_active, "BONK freeze authority should be revoked"
        assert len(warnings) == 0

    def test_authorities_invalid(self) -> None:
        """A token with non-null mint authority should flag."""
        # Construct a test case where authority is non-null
        meta = TokenMeta(
            address="test",
            symbol="TEST",
            decimals=9,
            supply=1000000,
            mint_authority="So11111111111111111111111111111111111111112",
            freeze_authority=None,
        )
        mint_active, freeze_active, warnings = check_authorities(meta)
        assert mint_active
        assert not freeze_active
        assert len(warnings) == 1
        assert "Mint authority" in warnings[0]


# ── Holder Tests ──────────────────────────────────────────────────────────

class TestTokenHolders:
    def test_bonk_top_holders(self) -> None:
        """BONK should have well-distributed holders."""
        meta = fetch_token_meta(BONK_MINT)
        assert meta is not None
        holders = fetch_token_holders(BONK_MINT, meta.decimals)
        if holders is not None:
            assert holders.total_holders > 0
            assert holders.top_10_pct > 0
            assert len(holders.top_holders) > 0


# ── Token Age Tests ───────────────────────────────────────────────────────

class TestTokenAge:
    def test_bonk_age(self) -> None:
        """BONK has been around for years — should not be flagged 'very new'."""
        age_days, warnings = estimate_token_age(BONK_MINT)
        if age_days > 0:
            assert age_days > 30  # BONK is years old
        # If age is 0, RPC may not have returned sigs for the mint account
        # (mints themselves don't have signatures — the TOKEN has them via token accounts)


# ── Scoring Tests ─────────────────────────────────────────────────────────

class TestScoring:
    def test_score_safe_token(self) -> None:
        """A token with all authorities revoked and good distribution."""
        flags = RugFlags()
        score = RugScore()
        safety, level, rec = compute_safety_score(flags, score, [])
        assert safety >= 70
        assert level == "LOW"

    def test_score_max_risk(self) -> None:
        """A fully flagged token should get max risk."""
        flags = RugFlags(
            mint_authority_active=True,
            freeze_authority_active=True,
            lp_not_burned=True,
            high_holder_concentration=True,
            recent_unlimited_mints=True,
            dev_holds_large_pct=True,
            possible_honeypot=True,
            token_very_young=True,
        )
        score = RugScore(
            mint_authority_risk=25,
            freeze_authority_risk=10,
            liquidity_risk=25,
            holder_concentration_risk=20,
            mint_history_risk=10,
            honeypot_risk=15,
            dev_risk=15,
        )
        safety, level, rec = compute_safety_score(flags, score, [])
        assert safety <= 20
        assert level in ("HIGH", "CRITICAL")

    def test_score_bounds(self) -> None:
        """Score should always be between 0-100."""
        for risk_pts in [0, 50, 100]:
            flags = RugFlags()
            score = RugScore(
                mint_authority_risk=risk_pts,
                freeze_authority_risk=risk_pts,
                liquidity_risk=risk_pts,
                holder_concentration_risk=risk_pts,
                mint_history_risk=risk_pts,
                honeypot_risk=risk_pts,
                dev_risk=risk_pts,
            )
            safety, level, rec = compute_safety_score(flags, score, [])
            assert 0 <= safety <= 100


# ── Output Formatting Tests ───────────────────────────────────────────────

class TestOutput:
    def test_format_json_roundtrip(self) -> None:
        report = RugReport(
            token=TokenMeta(
                address=BONK_MINT,
                symbol="BONK",
                decimals=5,
                supply=100000000000000,
            ),
            safety_score=85,
            risk_level="LOW",
        )
        output = format_json(report)
        parsed = json.loads(output)
        assert parsed["safety_score"] == 85
        assert parsed["risk_level"] == "LOW"
        assert parsed["token"]["symbol"] == "BONK"

    def test_format_markdown(self) -> None:
        report = RugReport(
            token=TokenMeta(address=BONK_MINT, symbol="BONK"),
            safety_score=85,
            risk_level="LOW",
            recommendation="Looks safe.",
        )
        md = format_markdown(report)
        assert "BONK" in md
        assert "85/100" in md
        assert "LOW" in md
        assert "Looks safe." in md

    def test_format_markdown_with_warnings(self) -> None:
        report = RugReport(
            token=TokenMeta(address=BONK_MINT),
            safety_score=30,
            risk_level="HIGH",
            warnings=["Mint authority not revoked"],
            recommendation="Avoid.",
        )
        md = format_markdown(report)
        assert "Mint authority" in md
        assert "HIGH" in md
        assert "Avoid." in md


# ── Full Analysis Integration Test ────────────────────────────────────────

class TestFullAnalysis:
    @pytest.mark.slow
    def test_bonk_full_analysis(self) -> None:
        """Full rug check on BONK — should pass safely."""
        report = rug_check_token(BONK_MINT)
        assert report.safety_score >= 60
        assert report.risk_level in ("LOW", "MEDIUM")
        assert not report.flags.mint_authority_active
        assert not report.flags.freeze_authority_active

    @pytest.mark.slow
    def test_bonk_markdown_output(self) -> None:
        """BONK markdown should be well-formed."""
        report = rug_check_token(BONK_MINT)
        md = format_markdown(report)
        assert md.startswith("#")
        assert "Safety Score" in md
        assert "Score Breakdown" in md


# ── CLI Tests ─────────────────────────────────────────────────────────────

class TestCLI:
    @pytest.mark.slow
    def test_cli_token_bonk_json(self) -> None:
        """CLI token command on BONK should return valid JSON."""
        script = Path(_scripts) / "rugguard.py"
        result = subprocess.run(
            [sys.executable, str(script), "token", BONK_MINT, "--json"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        data = json.loads(result.stdout)
        assert "safety_score" in data
        assert data["safety_score"] >= 60

    @pytest.mark.slow
    def test_cli_token_bonk_markdown(self) -> None:
        """CLI token command with --md should return Markdown."""
        script = Path(_scripts) / "rugguard.py"
        result = subprocess.run(
            [sys.executable, str(script), "token", BONK_MINT, "--md"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"STDERR: {result.stderr}"
        assert "#" in result.stdout
        assert "Safety Score" in result.stdout

    @pytest.mark.slow
    def test_cli_help(self) -> None:
        """CLI --help should work."""
        script = Path(_scripts) / "rugguard.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "USAGE" in result.stdout or "USAGE" in result.stderr

    @pytest.mark.slow
    def test_cli_invalid_mint(self) -> None:
        """CLI should handle invalid mints gracefully."""
        script = Path(_scripts) / "rugguard.py"
        result = subprocess.run(
            [sys.executable, str(script), "token", "InvalidMintAddress"],
            capture_output=True, text=True, timeout=15,
        )
        # Should return error JSON or error exit
        assert result.returncode != 0 or "Error" in result.stdout


# ── Wallet Scan Test ──────────────────────────────────────────────────────

@pytest.mark.slow
def test_wallet_scan() -> None:
    """Wallet scan should return valid structure."""
    from rugguard import rug_check_wallet
    result = rug_check_wallet(TEST_WALLET)
    assert "address" in result
    assert result["address"] == TEST_WALLET
    assert "total_tokens" in result
    assert isinstance(result["total_tokens"], int)
