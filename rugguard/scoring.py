#!/usr/bin/env python3
"""rugguard/scoring.py — Scoring engine for Solana Rug Guard.

Extracted from scripts/rugguard.py. Contains all data models and
scoring logic for rug-pull risk assessment.

MIT License — free, open-source, no paid APIs required.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from .rpc import _rpc_call

# ── Constants ────────────────────────────────────────────────────────────────

NULL_ADDRESS = "11111111111111111111111111111111"

LIQ_THRESHOLD_CRITICAL = int(os.environ.get("SOLANA_RUG_LIQ_THRESHOLD_CRITICAL", "1000"))
LIQ_THRESHOLD_HIGH = int(os.environ.get("SOLANA_RUG_LIQ_THRESHOLD_HIGH", "5000"))
LIQ_THRESHOLD_MEDIUM = int(os.environ.get("SOLANA_RUG_LIQ_THRESHOLD_MEDIUM", "20000"))
LIQ_THRESHOLD_LOW = int(os.environ.get("SOLANA_RUG_LIQ_THRESHOLD_LOW", "100000"))
LIQ_VOL_RATIO_WARNING = float(os.environ.get("SOLANA_RUG_LIQ_VOL_RATIO_WARNING", "15"))
LIQ_VOL_RATIO_MIN = float(os.environ.get("SOLANA_RUG_LIQ_VOL_RATIO_MIN", "0.05"))

SUSPICIOUS_TOKEN_KEYWORDS = [
    "rug", "scam", "ponzi", "honeypot", "drain", "phish", "shit",
    "moonbag", "pumpndump", "abandon", "test", "troll", "fake",
]

# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class RugFlags:
    mint_authority_active: bool = False
    freeze_authority_active: bool = False
    lp_not_burned: bool = False
    high_holder_concentration: bool = False
    recent_unlimited_mints: bool = False
    dev_holds_large_pct: bool = False
    possible_honeypot: bool = False
    token_very_young: bool = False
    sniper_detected: bool = False  # bots bought within first 10 transactions
    suspicious_name: bool = False  # token name contains red-flag keywords
    sub_penny_price: bool = False  # price is $0.000x or less
    deployer_can_crash_price: bool = False  # deployer hold % could crash the market
    flagged_warnings: list[str] = field(default_factory=list)


@dataclass
class RugScore:
    overall_score: int = 0  # 0-100+, higher = riskier
    mint_authority_risk: int = 0
    freeze_authority_risk: int = 0
    liquidity_risk: int = 0
    holder_concentration_risk: int = 0
    mint_history_risk: int = 0
    honeypot_risk: int = 0
    dev_risk: int = 0
    age_risk: int = 0
    low_liquidity_risk: int = 0
    sniper_risk: int = 0
    name_risk: int = 0
    sub_penny_risk: int = 0
    deployer_dump_risk: int = 0


# ── Core Analysis Functions ──────────────────────────────────────────────────


def check_authorities(token) -> tuple[bool, bool, list[str]]:
    """Check if mint/freeze authorities are revoked.
    Returns: (mint_active, freeze_active, warnings)"""
    warnings = []
    mint_active = False
    freeze_active = False

    if token.mint_authority and token.mint_authority != NULL_ADDRESS:
        mint_active = True
        short = f"{token.mint_authority[:4]}...{token.mint_authority[-4:]}"
        warnings.append(f"Mint authority NOT revoked ({short}) — dev can mint unlimited tokens")

    if token.freeze_authority and token.freeze_authority != NULL_ADDRESS:
        freeze_active = True
        short = f"{token.freeze_authority[:4]}...{token.freeze_authority[-4:]}"
        warnings.append(f"Freeze authority NOT revoked ({short}) — dev can freeze accounts")

    return mint_active, freeze_active, warnings


def check_sniper_patterns(mint: str, dex_data: dict | None = None) -> bool:
    """Check if bot snipers bought within the first 10 transactions.
    Returns True if suspicious buying pattern detected.

    For most SPL tokens, uses getSignaturesForAddress on the mint address.
    For Pump.fun / Token-2022 tokens, uses the pair/pool address from DexScreener
    since the actual buy transactions happen on the pool, not the mint.
    """
    cache_key = f"sniper:{mint}"
    cached = _get_sniper_cache(cache_key)
    if cached is not None:
        return cached

    # For Pump.fun / AMM tokens, check the pair address instead of the mint
    target = mint
    if dex_data and dex_data.get("pair_address"):
        # pumpSwap, raydium, meteora pools have buy activity on the pair address
        target = dex_data["pair_address"]

    sigs = _rpc_call("getSignaturesForAddress", [target, {"limit": 15}], retries=1, pin_rpc=True)
    if not sigs or len(sigs) < 5:
        _set_sniper_cache(cache_key, False)
        return False

    # Reverse to chronological order (oldest first)
    sigs.reverse()

    # Check the first 10 transactions — if multiple unique signers
    # bought in rapid succession, it's a sniping pattern
    first_10 = sigs[:10]
    rapid_buys = 0
    prev_slot = None

    for s in first_10:
        # Transactions within 50 slots (~20 seconds) of each other
        # is likely sniping (Pump.fun creates distinct program accounts
        # between mint-address transactions, widening the slot gap)
        slot = s.get("slot", 0)
        if prev_slot is not None and (slot - prev_slot) <= 50:
            rapid_buys += 1
        prev_slot = slot

    # If 3+ buys happened within 50 slots of each other, it's sniping
    result = rapid_buys >= 3
    _set_sniper_cache(cache_key, result)
    return result


# Simple caching helpers for sniper checks (keeps function self-contained)
_sniper_cache: dict[str, bool] = {}

def _get_sniper_cache(key: str) -> bool | None:
    return _sniper_cache.get(key)

def _set_sniper_cache(key: str, value: bool) -> None:
    _sniper_cache[key] = value


def check_suspicious_name(name: str, symbol: str) -> bool:
    """Check token name/symbol for red-flag keywords."""
    combined = (name + " " + symbol).lower()
    for kw in SUSPICIOUS_TOKEN_KEYWORDS:
        if kw in combined:
            return True
    return False


def compute_deployer_dump_risk(deployer_hold_pct: float, liquidity_usd: float) -> tuple[bool, str]:
    """Check if deployer could crash price by selling.
    Returns (is_risky, explanation)."""
    if deployer_hold_pct <= 0 or liquidity_usd <= 0:
        return (False, "")
    deployer_value = deployer_hold_pct / 100.0 * liquidity_usd
    if deployer_value > liquidity_usd * 0.5:
        return (True, f"Deployer's holdings worth ~${deployer_value:,.0f} — could crash the {liquidity_usd:,.0f} pool")
    if deployer_hold_pct > 10:
        return (True, f"Deployer holds {deployer_hold_pct:.1f}% — selling would crater price")
    return (False, "")


# ── Scoring Engine ─────────────────────────────────────────────────────────


def compute_safety_score(
    flags: RugFlags,
    score: RugScore,
    warnings: list[str],
) -> tuple[int, str, str]:
    """Compute final safety score and recommendation."""
    overall = sum([
        score.mint_authority_risk,
        score.freeze_authority_risk,
        score.liquidity_risk,
        score.holder_concentration_risk,
        score.mint_history_risk,
        score.honeypot_risk,
        score.dev_risk,
        score.age_risk,
        score.low_liquidity_risk,
        score.sniper_risk,
        score.name_risk,
        score.sub_penny_risk,
        score.deployer_dump_risk,
    ])
    overall = max(0, overall)  # no upper cap — more risks = lower safety
    safety = max(0, 100 - overall)

    if safety >= 70:
        level = "LOW"
        rec = "Token appears safe — standard risks only."
    elif safety >= 40:
        level = "MEDIUM"
        rec = "Moderate risk detected. Proceed with caution — review flagged warnings."
    elif safety >= 20:
        level = "HIGH"
        rec = "High rug risk. Multiple red flags — consider avoiding this token."
    else:
        level = "CRITICAL"
        rec = "Critical rug risk. Strong evidence of malicious setup — DO NOT buy."

    if warnings:
        rec += f"\nWarnings: {'; '.join(warnings[:5])}"

    return safety, level, rec


def compute_score_components(
    flags: RugFlags, token, holders,
    liquidity, mint_history,
    honeypot,
    dex_data: dict | None = None,
) -> tuple[RugScore, list[str]]:
    """Compute each risk component and gather warnings."""
    warnings = []
    score = RugScore()

    # 1. Mint authority (20 pts)
    if flags.mint_authority_active:
        score.mint_authority_risk = 20
        warnings.append("Mint authority active — dev can mint unlimited tokens")

    # 2. Freeze authority (10 pts)
    if flags.freeze_authority_active:
        score.freeze_authority_risk = 10
        warnings.append("Freeze authority active — dev can freeze accounts")

    # 3. Liquidity — locked/burned check (20 pts)
    if flags.lp_not_burned:
        score.liquidity_risk = 20
        warnings.append("LP tokens not burned — dev can pull liquidity")
    elif liquidity and not liquidity.has_lp:
        score.liquidity_risk = 15
        warnings.append("No LP detected — token may be untradeable")

    # 3b. Liquidity — size/thin check (5 pts, dynamically scaled)
    liq = 0
    vol = 0
    if dex_data:
        liq = dex_data.get("liquidity_usd", 0) or 0
        vol = dex_data.get("volume_24h", 0) or 0
    elif liquidity and liquidity.has_lp and liquidity.liquidity_usd > 0:
        liq = liquidity.liquidity_usd
        # No dex_data means no 24h volume available
        vol = 0

    if dex_data and liq <= 0:
        # DexScreener reports the pair but liquidity is $0 — the pair exists
        # but has no real backing (often a honeypot or dead pool)
        score.low_liquidity_risk = 5
        warnings.append("Pair exists with zero liquidity — token may be untradeable")
    elif liq > 0:
        if liq < LIQ_THRESHOLD_CRITICAL:
            score.low_liquidity_risk = 5
            warnings.append(f"Extremely thin liquidity (${liq:,.0f}) — one sell can crash price")
        elif liq < LIQ_THRESHOLD_HIGH:
            score.low_liquidity_risk = 4
            warnings.append(f"Very thin liquidity (${liq:,.0f}) — significant price impact on trades")
        elif liq < LIQ_THRESHOLD_MEDIUM:
            score.low_liquidity_risk = 3
            warnings.append(f"Thin liquidity (${liq:,.0f}) — moderate price impact on trades")
        elif liq < LIQ_THRESHOLD_LOW:
            score.low_liquidity_risk = 1
            warnings.append(f"Moderate liquidity (${liq:,.0f}) — some price impact possible")

        # Volume-to-liquidity ratio — high ratio suggests wash trading or
        # rapid churn relative to pool depth (unhealthy)
        if vol > 0 and liq > 0:
            ratio = vol / liq
            if ratio > LIQ_VOL_RATIO_WARNING:
                score.low_liquidity_risk = max(score.low_liquidity_risk, 3)
                warnings.append(
                    f"High volume/liquidity ratio ({ratio:.1f}x) — "
                    f"${vol:,.0f} volume on ${liq:,.0f} liquidity — possible wash trading"
                )
            # Low ratio suggests a dead/inactive pool with no trading activity
            if ratio < LIQ_VOL_RATIO_MIN:
                score.low_liquidity_risk = max(score.low_liquidity_risk, 3)
                warnings.append(
                    f"Low volume/liquidity ratio ({ratio:.3f}x) — "
                    f"${vol:,.0f} volume on ${liq:,.0f} liquidity — pool may be inactive"
                )

    # 4. Holder concentration (15 pts)
    if holders:
        if holders.top_10_pct > 90:
            score.holder_concentration_risk = 15
            warnings.append(f"Top 10 holders own {holders.top_10_pct:.1f}% of supply — extreme concentration")
        elif holders.top_10_pct > 70:
            score.holder_concentration_risk = 12
            warnings.append(f"Top 10 holders own {holders.top_10_pct:.1f}% of supply — high concentration")
        elif holders.top_10_pct > 50:
            score.holder_concentration_risk = 8
            warnings.append(f"Top 10 holders own {holders.top_10_pct:.1f}% of supply")

        if holders.dev_wallet_pct > 30:
            score.dev_risk = max(score.dev_risk, 10)
            warnings.append(f"Dev wallet holds {holders.dev_wallet_pct:.1f}% of supply")
        elif holders.dev_wallet_pct > 15:
            score.dev_risk = max(score.dev_risk, 5)
            warnings.append(f"Dev wallet holds {holders.dev_wallet_pct:.1f}% of supply")

        # Low holder count (small community = risky)
        if holders.total_holders < 10:
            score.holder_concentration_risk = max(score.holder_concentration_risk, 5)
            warnings.append(f"Very few holders ({holders.total_holders}) — concentrated risk")
        elif holders.total_holders < 50:
            score.holder_concentration_risk = max(score.holder_concentration_risk, 3)
            warnings.append(f"Small holder base ({holders.total_holders})")

    # 5. Token age risk (5 pts)
    if flags.token_very_young:
        score.age_risk = 5
    elif token.supply > 0:
        # Check via dex_data age
        if dex_data and dex_data.get("created_at_ms"):
            age_days = (time.time() - dex_data["created_at_ms"] / 1000) / 86400
            if age_days < 7:
                score.age_risk = 3
                warnings.append(f"Token is only {age_days:.1f} days old — still early stage")

    # 6. Mint history (5 pts)
    if mint_history and mint_history.recent_mints > 5:
        score.mint_history_risk = 5
        warnings.append(f"{mint_history.recent_mints} recent mints to deployer after launch")
    elif mint_history and mint_history.recent_mints > 0:
        score.mint_history_risk = 3
        warnings.append(f"{mint_history.recent_mints} mint(s) to deployer after launch")

    # 7. Honeypot (10 pts)
    if honeypot and not honeypot.can_trade:
        score.honeypot_risk = 10
        warnings.append(f"Token may be a honeypot — cannot sell: {honeypot.error or 'unknown reason'}")

    # 8. Sniper detection (10 pts) — bots buying in first 10 transactions
    if flags.sniper_detected:
        score.sniper_risk = 10
        warnings.append("Sniping pattern detected — bot wallets bought within first seconds of launch")

    # 9. Suspicious name check (5 pts)
    if flags.suspicious_name:
        score.name_risk = 5
        warnings.append("Suspicious token name detected — discourages organic buyers")

    # 10. Sub-penny price risk (5 pts)
    if flags.sub_penny_price:
        score.sub_penny_risk = 5
        warnings.append("Sub-penny price — typical of dead/low-activity tokens")

    # 11. Deployer can crash price (5 pts)
    if flags.deployer_can_crash_price:
        score.deployer_dump_risk = 5
        warnings.append("Deployer holds significant supply — a single sell could crash price")

    return score, warnings
