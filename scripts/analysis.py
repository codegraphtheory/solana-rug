from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from onchain import (
    HolderInfo,
    HoneypotResult,
    LiquidityInfo,
    MintHistory,
    TokenMeta,
    _dex_screener_fetch,
    check_honeypot,
    check_mint_history,
    detect_liquidity_pools,
    estimate_token_age,
    fetch_token_holders,
    fetch_token_meta,
    resolve_deployer,
)
from rpc import _rpc_call
from scoring import (
    RugFlags,
    RugScore,
    check_authorities,
    check_sniper_patterns,
    check_suspicious_name,
    compute_deployer_dump_risk,
    compute_safety_score,
    compute_score_components,
)


@dataclass
class RugReport:
    token: TokenMeta
    safety_score: int = 100
    risk_level: str = "UNKNOWN"
    score: RugScore = field(default_factory=RugScore)
    flags: RugFlags = field(default_factory=RugFlags)
    holders: HolderInfo | None = None
    liquidity: LiquidityInfo | None = None
    mint_history: MintHistory | None = None
    honeypot: HoneypotResult | None = None
    recommendation: str = ""
    warnings: list[str] = field(default_factory=list)
    # Market data from DexScreener enrichment
    dex_data: dict | None = None

    def to_dict(self) -> dict:
        flags_dict = {}
        for k, v in asdict(self.flags).items():
            if k != "flagged_warnings":
                flags_dict[k] = v
        result = {
            "token": asdict(self.token),
            "safety_score": self.safety_score,
            "risk_level": self.risk_level,
            "score": asdict(self.score),
            "flags": flags_dict,
            "warnings": self.flags.flagged_warnings,
            "recommendation": self.recommendation,
        }
        if self.dex_data:
            result["market_data"] = {
                "dex": self.dex_data.get("dex", ""),
                "liquidity_usd": self.dex_data.get("liquidity_usd", 0),
                "volume_24h": self.dex_data.get("volume_24h", 0),
                "price_usd": self.dex_data.get("price_usd", 0),
                "price_change_24h": self.dex_data.get("price_change_24h", 0),
            }
        return result


def rug_check_token(mint: str) -> RugReport:
    """Run full rug-check analysis on a single token mint address."""
    # 1. Fetch token metadata
    token = fetch_token_meta(mint)
    if not token:
        return RugReport(
            token=TokenMeta(address=mint),
            safety_score=0,
            risk_level="ERROR",
            recommendation=f"Could not fetch token metadata for {mint}. Check the address.",
            warnings=[f"Failed to fetch account info for {mint}"],
        )

    # 2. Authority checks
    mint_active, freeze_active, auth_warnings = check_authorities(token)
    flags = RugFlags(
        mint_authority_active=mint_active,
        freeze_authority_active=freeze_active,
    )

    # Check Token-2022 extensions for hidden risks
    ext_warnings = []
    if "TokenzQd" in token.token_program:
        for ext in token.extensions:
            el = ext.lower()
            if "transferfee" in el or "transfer fee" in el:
                ext_warnings.append("Token-2022 transfer fee extension — tax on every transfer")
            elif "transferhook" in el or "transfer hook" in el:
                ext_warnings.append("Token-2022 transfer hook — transfers may be restricted")
            elif "larg" in el:  # large-acct-size
                ext_warnings.append("Token-2022 with non-standard extensions — inspect further")

    # 3. Holder analysis
    holders = fetch_token_holders(mint, token.decimals)
    if holders:
        flags.high_holder_concentration = holders.top_10_pct > 50
        flags.dev_holds_large_pct = holders.dev_wallet_pct > 15

    # 4. Liquidity pools
    liquidity = detect_liquidity_pools(mint)
    if liquidity:
        flags.lp_not_burned = liquidity.has_lp and not liquidity.lp_burned

    # 5. Deployer and mint history
    deployer = resolve_deployer(mint)
    mint_history = check_mint_history(mint, deployer) if deployer else None
    if mint_history and mint_history.recent_mints > 0:
        flags.recent_unlimited_mints = True

    # 6. Honeypot check
    honeypot = check_honeypot(mint)
    if honeypot and not honeypot.can_trade:
        flags.possible_honeypot = True

    # 7. Token age (with DexScreener fallback)
    age_days, age_warnings = estimate_token_age(mint)
    if age_days < 1:
        flags.token_very_young = True

    # 8. Sniper pattern detection (runs after dex_data for pool-address fallback)

    # 9. Suspicious name check (tokenMetadata + DexScreener fallback)
    if check_suspicious_name(token.name, token.symbol):
        flags.suspicious_name = True

    # 10. Enrich with DexScreener market data (needed for scoring)
    dex_data = _dex_screener_fetch(mint)

    # Also check name from DexScreener if on-chain metadata was empty
    if not flags.suspicious_name and dex_data:
        dex_symbol = dex_data.get("base_symbol", "")
        if check_suspicious_name(dex_symbol, dex_symbol):
            flags.suspicious_name = True
            if not token.symbol:
                token.symbol = dex_symbol

    # 11. Additional checks that depend on dex_data
    if dex_data:
        # Sub-penny price check (skip for well-established tokens with deep liquidity)
        price = dex_data.get("price_usd", 0)
        liq = dex_data.get("liquidity_usd", 0) or (liquidity.liquidity_usd if liquidity else 0)
        age_d = dex_data.get("created_at_ms", 0)
        if age_d:
            age_d = (time.time() - age_d / 1000) / 86400
        if 0 < price < 0.0001:
            # Only flag if token is young OR has thin liquidity
            if age_d < 30 or liq < 100000:
                flags.sub_penny_price = True

        # Deployer dump risk (skip for old tokens — first holder is likely a pool)
        if holders and holders.dev_wallet_pct > 0 and age_d < 30:
            risky, _ = compute_deployer_dump_risk(holders.dev_wallet_pct, liq)
            if risky:
                flags.deployer_can_crash_price = True

    # Sniper pattern detection (after dex_data so we can use pool address for Pump.fun)
    if check_sniper_patterns(mint, dex_data):
        flags.sniper_detected = True

    # 11. Compute score (now includes dex_data for thin liquidity, age checks)
    score, score_warnings = compute_score_components(
        flags,
        token,
        holders,
        liquidity,
        mint_history,
        honeypot,
        dex_data=dex_data,
    )
    all_warnings = auth_warnings + ext_warnings + age_warnings + score_warnings

    # 10. Final safety score
    safety, level, rec = compute_safety_score(flags, score, all_warnings)

    return RugReport(
        token=token,
        safety_score=safety,
        risk_level=level,
        score=score,
        flags=flags,
        holders=holders,
        liquidity=liquidity,
        mint_history=mint_history,
        honeypot=honeypot,
        recommendation=rec,
        warnings=list(dict.fromkeys(all_warnings)),
        dex_data=dex_data,
    )


def rug_check_wallet(address: str) -> dict:
    """Scan a wallet for risky tokens held."""
    result = _rpc_call(
        "getTokenAccountsByOwner",
        [
            address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"},
        ],
    )
    if not result or "value" not in result:
        return {
            "address": address,
            "error": "Could not fetch wallet token accounts",
            "total_tokens": 0,
            "risky_tokens": [],
            "summary": "Wallet scan failed — RPC error.",
        }

    tokens = result["value"]
    risky_tokens = []

    for token_acct in tokens:
        acct_data = token_acct.get("account", {}).get("data", {}).get("parsed", {}).get("info", {})
        mint = acct_data.get("mint", "")
        amount = int(acct_data.get("tokenAmount", {}).get("amount", "0"))
        decimals = acct_data.get("tokenAmount", {}).get("decimals", 0)

        if amount == 0:
            continue

        # Only scan tokens with meaningful value (more than 0.01 in raw amount)
        if decimals > 0 and amount > 10 ** (decimals - 4):
            # Quick check: just metadata + authorities (fast, no LP/holders)
            token = fetch_token_meta(mint)
            if not token:
                continue
            mint_active, _, a_warnings = check_authorities(token)
            # Quick risk: mint not revoked = high risk
            quick_safety = 50 if mint_active else 80
            quick_level = "HIGH" if mint_active else "MEDIUM"
            if quick_safety < 60:
                risky_tokens.append(
                    {
                        "mint": mint,
                        "symbol": token.symbol or f"{mint[:4]}...{mint[-4:]}",
                        "balance_raw": amount,
                        "decimals": decimals,
                        "safety_score": quick_safety,
                        "risk_level": quick_level,
                        "top_warnings": a_warnings[:3],
                    }
                )

    risky_tokens.sort(key=lambda t: t["safety_score"])
    total_tokens = len(tokens)
    risky_count = len(risky_tokens)

    if risky_count == 0:
        summary = f"✅ No high-risk tokens detected among {total_tokens} token accounts."
    else:
        summary = (
            f"⚠️ Found {risky_count} risky token{'s' if risky_count > 1 else ''} "
            f"out of {total_tokens} token accounts scanned."
        )

    return {
        "address": address,
        "total_tokens": total_tokens,
        "risky_count": risky_count,
        "risky_tokens": risky_tokens,
        "summary": summary,
    }
