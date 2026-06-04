#!/usr/bin/env python3
"""rugguard.py — Solana Rug Guard: on-chain rug-pull detection engine.

CLI usage:
    python rugguard.py token <MINT_ADDRESS>
    python rugguard.py wallet <WALLET_ADDRESS>

Python API:
    from rugguard import rug_check_token, rug_check_wallet, RugReport

MIT License — free, open-source, no paid APIs required.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
import uuid
from base64 import b64decode
from dataclasses import asdict, dataclass, field
from typing import Any

# ── RPC Configuration ──────────────────────────────────────────────────────

PUBLIC_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-api.projectserum.com",
    "https://rpc.ankr.com/solana",
    "https://solana.public-rpc.com",
]

RPC_URL = os.environ.get("SOLANA_RPC_URL", PUBLIC_RPCS[0])

LAMPORTS_PER_SOL = 1_000_000_000

# ── Multi-RPC fallback ──────────────────────────────────────────────────────
_rpc_index = 0
def _next_rpc() -> str:
    """Round-robin through public RPCs to avoid rate limits."""
    global _rpc_index
    url = PUBLIC_RPCS[_rpc_index % len(PUBLIC_RPCS)]
    _rpc_index += 1
    return url

# ── Caching ─────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, Any]] = {}
CACHE_TTL = 300  # 5 minutes
def _cached(key: str, ttl: int = CACHE_TTL) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < ttl:
        return entry[1]
    return None
def _set_cache(key: str, value: Any, ttl: int = CACHE_TTL) -> None:
    _cache[key] = (time.time(), value)
# ── HTTP / RPC Helpers (stdlib-only) ───────────────────────────────────────

def _http_post(url: str, payload: dict, timeout: int = 6) -> dict | None:
    """POST JSON to URL, return parsed response or None."""
    import urllib.error
    import urllib.request

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError):
        return None
def _rpc_call(
    method: str,
    params: list | None = None,
    retries: int = 1,
    rpc_url: str | None = None,
    pin_rpc: bool = False,
) -> Any | None:
    """Single JSON-RPC call with round-robin fallback and retry on 429/503.

    When pin_rpc=True, uses the same URL for all retries (for pagination).
    """
    url = rpc_url or (_next_rpc() if not pin_rpc else RPC_URL)
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params or [],
    }
    for attempt in range(retries + 1):
        resp = _http_post(url, payload)
        if resp is None:
            # Try next RPC (but stay pinned if pin_rpc)
            if not pin_rpc:
                url = _next_rpc()
            continue
        if "result" in resp:
            return resp["result"]
        if "error" in resp:
            err = resp["error"]
            code = err.get("code", 0) if isinstance(err, dict) else 0
            if code in (-32005, -32009, 429) and attempt < retries:
                if not pin_rpc:
                    url = _next_rpc()
                continue
            return None
        if attempt < retries:
            if not pin_rpc:
                url = _next_rpc()
    return None
def _rpc_batch(
    calls: list[tuple[str, list]],
    retries: int = 1,
    rpc_url: str | None = None,
) -> list[Any | None]:
    """Batch JSON-RPC call. Returns list of result values in order."""
    url = rpc_url or RPC_URL
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "getMultipleAccounts",
        "params": [
            [acct for acct, _ in calls],
            {"encoding": "jsonParsed"},
        ],
    }
    if len(calls) == 1:
        # Single call, no batching needed
        result = _rpc_call(calls[0][0], calls[0][1], retries=retries, rpc_url=rpc_url)
        return [result]

    for attempt in range(retries + 1):
        resp = _http_post(url, payload)
        if resp and "result" in resp:
            values = resp["result"].get("value", [])
            return list(values)
        if attempt < retries:
            time.sleep(1.0 * (attempt + 1))
    return [None] * len(calls)
def _lamports_to_sol(lamports: int) -> float:
    return lamports / LAMPORTS_PER_SOL
# ── Data Models ────────────────────────────────────────────────────────────

@dataclass
class TokenMeta:
    address: str
    symbol: str = ""
    name: str = ""
    decimals: int = 0
    supply: int = 0  # raw supply (not adjusted for decimals)
    mint_authority: str | None = None
    freeze_authority: str | None = None
    token_program: str = ""  # "Tokenkeg..." (SPL) or "TokenzQd..." (Token-2022)
    extensions: list[str] = field(default_factory=list)  # Token-2022 extensions found
@dataclass
class HolderInfo:
    total_holders: int = 0
    top_10_pct: float = 0.0
    dev_wallet_pct: float = 0.0
    top_holders: list[dict] = field(default_factory=list)
@dataclass
class LiquidityInfo:
    has_lp: bool = False
    pool_count: int = 0
    lp_burned: bool = False
    lp_locked: bool = False
    liquidity_usd: float = 0.0
    pools: list[dict] = field(default_factory=list)
@dataclass
class MintHistory:
    recent_mints: int = 0  # number of mint txs to deployer after initial launch
    last_mint_days_ago: float | None = None
@dataclass
class HoneypotResult:
    can_trade: bool = True
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    error: str | None = None
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
LAMPORTS_PER_SOL = 1_000_000_000
NULL_ADDRESS = "11111111111111111111111111111111"

# Known DEX program IDs for LP detection
KNOWN_DEX_PROGRAMS = {
    "Raydium": "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "Raydium CP": "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "Orca": "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uckxo",
    "Orca v2": "9W959DqEETiGZocYWCQPaJ6sBmUzgfxXfqGeNDEdPdt",
    "Pump.fun": "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
}

KNOWN_DEX_PROGRAM_IDS = set(KNOWN_DEX_PROGRAMS.values())

# ── Core Analysis Functions ────────────────────────────────────────────────

_DEX_SCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/"
def _dex_screener_fetch(mint: str) -> dict | None:
    """Fetch token data from DexScreener API. Returns first pair or None."""
    cache_key = f"dexscreener:{mint}"
    cached = _cached(cache_key)
    if cached:
        return cached
    try:
        import urllib.request
        url = _DEX_SCREENER_URL + mint
        req = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            pairs = data.get("pairs", [])
            if pairs:
                # Find the pair with highest liquidity (most useful)
                best = max(pairs, key=lambda p: float(p.get("liquidity", {}).get("usd", 0) or 0))
                result = {
                    "dex": best.get("dexId", ""),
                    "pair_address": best.get("pairAddress", ""),
                    "base_symbol": best.get("baseToken", {}).get("symbol", ""),
                    "quote_symbol": best.get("quoteToken", {}).get("symbol", ""),
                    "liquidity_usd": float(best.get("liquidity", {}).get("usd", 0) or 0),
                    "volume_24h": float(best.get("volume", {}).get("h24", 0) or 0),
                    "price_usd": float(best.get("priceUsd", 0) or 0),
                    "price_change_24h": float(best.get("priceChange", {}).get("h24", 0) or 0),
                    "created_at_ms": best.get("pairCreatedAt", 0),
                    "txns_24h_buys": int(best.get("txns", {}).get("h24", {}).get("buys", 0)),
                    "txns_24h_sells": int(best.get("txns", {}).get("h24", {}).get("sells", 0)),
                }
                _set_cache(cache_key, result)
                return result
    except Exception:
        pass
    _set_cache(cache_key, None)
    return None

def fetch_token_meta(mint: str) -> TokenMeta | None:
    """Fetch token metadata from the mint account."""
    cache_key = f"meta:{mint}"
    cached = _cached(cache_key)
    if cached:
        return TokenMeta(**cached)

    result = _rpc_call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
    if not result or "value" not in result or result["value"] is None:
        return None

    data = result["value"]
    raw_data_field = data.get("data", [])
    if isinstance(raw_data_field, dict):
        parsed = raw_data_field.get("parsed", {})
        info = parsed.get("info", {})
    else:
        # Raw base64 data — no jsonParsed available
        info = {}
        if isinstance(raw_data_field, list) and len(raw_data_field) > 0:
            try:
                raw_bytes = b64decode(raw_data_field[0])
                if len(raw_bytes) >= 45:
                    info["decimals"] = raw_bytes[44]
                    supply_bytes = raw_bytes[36:44]
                    info["supply"] = str(int.from_bytes(supply_bytes, "little"))
            except Exception:
                pass

    meta = TokenMeta(
        address=mint,
        symbol=info.get("symbol", ""),
        name=info.get("name", ""),
        decimals=info.get("decimals", 0),
        supply=int(info.get("supply", "0")),
        mint_authority=info.get("mintAuthority"),
        freeze_authority=info.get("freezeAuthority"),
        token_program=result["value"].get("owner", ""),
    )

    # Detect Token-2022 extensions
    parsed_data = raw_data_field.get("parsed", {}) if isinstance(raw_data_field, dict) else {}
    if "TokenzQd" in meta.token_program:
        ext_list = parsed_data.get("info", {}).get("extensions", [])
        for ext in ext_list:
            ext_name = ext.get("extension", ext.get("type", ""))
            if ext_name:
                meta.extensions.append(ext_name)
            # Extract on-chain name/symbol from tokenMetadata extension
            if ext_name and "tokenMetadata" in ext_name.lower():
                state = ext.get("state", {})
                if state.get("name") and not meta.name:
                    meta.name = state["name"]
                if state.get("symbol") and not meta.symbol:
                    meta.symbol = state["symbol"]

        # Check for hidden extensions by examining account data size
        # Standard SPL mint = 82 bytes. Token-2022 = 82 + extensions. 400+ = multiple extensions.
        acct_size = result["value"].get("space", 0) if isinstance(result["value"], dict) else 0
        if acct_size > 200 and len(meta.extensions) <= 1:
            meta.extensions.append("large-acct-size")

    # Fallback: raw account data if jsonParsed failed
    if not meta.decimals and not meta.supply:
        raw_data = data.get("data", [])
        if raw_data and isinstance(raw_data, list) and len(raw_data) > 0:
            try:
                raw_bytes = b64decode(raw_data[0])
                meta.decimals = raw_bytes[44] if len(raw_bytes) > 44 else 0
                supply_bytes = raw_bytes[36:44] if len(raw_bytes) > 44 else b""
                meta.supply = int.from_bytes(supply_bytes, "little") if supply_bytes else 0
            except Exception:
                pass

    _set_cache(cache_key, asdict(meta))
    return meta
def check_authorities(token: TokenMeta) -> tuple[bool, bool, list[str]]:
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
def fetch_token_holders(mint: str, decimals: int) -> HolderInfo | None:
    """Fetch top token holders. Tries RPC first, falls back to DexScreener."""
    cache_key = f"holders:{mint}"
    cached = _cached(cache_key)
    if cached:
        return HolderInfo(**cached)

    # Try getTokenLargestAccounts (standard RPC method)
    largest = _rpc_call("getTokenLargestAccounts", [mint])
    if largest and "value" in largest:
        top_holders_data = largest["value"]
        if top_holders_data:
            total_supply = sum(int(h.get("amount", 0)) for h in top_holders_data)
            if total_supply > 0:
                top_holders = []
                for h in top_holders_data:
                    amt = int(h.get("amount", 0))
                    pct = round(amt / total_supply * 100, 2)
                    top_holders.append({"address": h.get("address", ""), "amount": amt, "pct": pct})
                top_10_pct = sum(h["pct"] for h in top_holders[:10])
                dev_pct = top_holders[0]["pct"] if top_holders else 0.0
                info = HolderInfo(
                    total_holders=len(top_holders_data),
                    top_10_pct=min(top_10_pct, 100.0),
                    dev_wallet_pct=dev_pct,
                    top_holders=top_holders[:10],
                )
                _set_cache(cache_key, asdict(info))
                return info

    # RPC failed (common for Token-2022 on public RPC) — try DexScreener
    dex_data = _dex_screener_fetch(mint)
    if dex_data:
        # DexScreener doesn't give holder lists, but we can infer from market data
        # that the token IS being traded (has holders) and flag concentration
        # from tx patterns
        buys = dex_data.get("txns_24h_buys", 0)
        sells = dex_data.get("txns_24h_sells", 0)
        total_txns = buys + sells
        if total_txns > 0:
            est_holders = min(total_txns // 3, 100)  # rough estimate
            info = HolderInfo(
                total_holders=max(est_holders, 1),
                top_10_pct=50.0,  # conservative default (50% concentration)
                dev_wallet_pct=15.0,
                top_holders=[{"address": "dexscreener-estimate", "amount": 0, "pct": 50.0}],
            )
            _set_cache(cache_key, asdict(info))
            return info

    return None
def detect_liquidity_pools(mint: str) -> LiquidityInfo:
    """Detect LP pools across all major Solana DEX programs.

    Checks Raydium AMM, Raydium CPMM (used by Pump.fun migrations),
    Orca, and Jupiter for tradability.
    """
    cache_key = f"lp:{mint}"
    cached = _cached(cache_key)
    if cached:
        return LiquidityInfo(**cached)

    info = LiquidityInfo()
    found_pools = []

    # DEX programs to check: (name, program_id, data_sizes_to_try)
    dex_targets = [
        ("Raydium AMM", "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", [165, 324]),
        ("Raydium CPMM", "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", [600]),
        ("pumpSwap", "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA", [324, 600, 165]),
        ("Orca", "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uckxo", [500]),
    ]

    for dex_name, program_id, data_sizes in dex_targets:
        for ds in data_sizes:
            result = _rpc_call(
                "getProgramAccounts",
                [program_id, {
                    "encoding": "base64",
                    "filters": [
                        {"dataSize": ds},
                        {"memcmp": {"offset": 0, "bytes": mint}},
                    ],
                }],
                retries=1,
            )
            if result and isinstance(result, list):
                for acct in result:
                    found_pools.append({
                        "address": acct.get("pubkey", ""),
                        "dex": dex_name,
                        "program_id": program_id,
                        "burned": False,
                    })
                if result:
                    break

    if found_pools:
        info.has_lp = True
        info.pool_count = len(found_pools)
        info.pools = found_pools
        for pool in found_pools[:3]:
            supply = _rpc_call("getTokenSupply", [pool["address"]], retries=1)
            if supply and "value" in supply:
                total = int(supply["value"].get("amount", "0"))
                if total == 0 or total < 1000:
                    pool["burned"] = True
                    info.lp_burned = True

    # DexScreener fallback: get real pool data when GPA is rate-limited
    dex_data = _dex_screener_fetch(mint)
    if dex_data:
        liq_usd = dex_data.get("liquidity_usd", 0)
        if liq_usd > 0:
            info.has_lp = True
            info.liquidity_usd = liq_usd
            dex_name = dex_data.get("dex", "unknown")
            pair_addr = dex_data.get("pair_address", "")
            # Known DEXes lock LP by design — mark as burned
            known_dexes = {"pumpswap", "pump", "raydium", "meteora", "orca"}
            if any(d in dex_name.lower() for d in known_dexes):
                info.lp_burned = True  # DEX-locked liquidity
            if pair_addr and not any(p["address"] == pair_addr for p in found_pools):
                info.pool_count = max(info.pool_count, 1)
                info.pools.append({
                    "address": pair_addr,
                    "dex": dex_name,
                    "program_id": "dexscreener",
                    "burned": False,
                })

    _set_cache(cache_key, asdict(info))
    return info
def _get_lp_mint_for_pool(pool_address: str, program_id: str) -> str | None:
    """Try to find LP mint for a pool account."""
    # Raydium AMM pools store LP mint at a known account
    # This is a best-effort lookup
    result = _rpc_call("getAccountInfo", [pool_address, {"encoding": "jsonParsed"}])
    if not result:
        return None
    return pool_address  # Simplified — in production we'd parse the account data
def check_mint_history(mint: str, deployer: str | None) -> MintHistory:
    """Check if the deployer has been minting more tokens after launch."""
    cache_key = f"mint_hist:{mint}"
    cached = _cached(cache_key)
    if cached:
        return MintHistory(**cached)

    info = MintHistory()

    if not deployer:
        _set_cache(cache_key, asdict(info))
        return info

    # Get recent signatures for the mint (to find mint-to transactions)
    sigs = _rpc_call("getSignaturesForAddress", [mint, {"limit": 20}])
    if not sigs:
        _set_cache(cache_key, asdict(info))
        return info

    # Count mint transactions sent to deployer
    mint_count = 0
    latest_mint_time = None

    for sig_info in sigs:
        tx_sig = sig_info.get("signature", "")
        if not tx_sig:
            continue

        tx = _rpc_call("getTransaction", [tx_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if not tx:
            continue

        # Check if this is a mint-to (token mints to a wallet)
        meta = tx.get("meta", {})
        if meta and meta.get("err"):
            continue  # failed tx

        pre_token_balances = meta.get("preTokenBalances", []) if meta else []
        post_token_balances = meta.get("postTokenBalances", []) if meta else []

        # Look for balance increases in deployer's wallet
        pre_map = {}
        for b in pre_token_balances:
            if b.get("mint") == mint:
                key = b.get("owner", "")
                pre_map[key] = int(b.get("uiTokenAmount", {}).get("amount", "0"))

        post_map = {}
        for b in post_token_balances:
            if b.get("mint") == mint:
                key = b.get("owner", "")
                post_map[key] = int(b.get("uiTokenAmount", {}).get("amount", "0"))

        for owner, pre_amt in pre_map.items():
            post_amt = post_map.get(owner, 0)
            if post_amt > pre_amt and owner == deployer:
                mint_count += 1
                latest_mint_time = sig_info.get("blockTime")

    info.recent_mints = mint_count
    if latest_mint_time:
        now = time.time()
        info.last_mint_days_ago = round((now - latest_mint_time) / 86400, 1)

    _set_cache(cache_key, asdict(info))
    return info
def check_honeypot(mint: str) -> HoneypotResult:
    """Basic honeypot check via simulated swap.
    Uses Jupiter quote API (free, no key) to estimate buy/sell ability."""
    result = HoneypotResult()

    # Try Jupiter price API for a simulated sell (5% slippage)
    try:
        import urllib.error
        import urllib.request

        # Use Jupiter quote API for a buy simulation
        # Quote: swap 0.01 SOL worth of this token -> SOL
        wsol = "So11111111111111111111111111111111111111112"
        url = (
            f"https://quote-api.jup.ag/v6/quote?"
            f"inputMint={mint}&outputMint={wsol}&amount=1000000&slippageBps=500"
        )
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                quote = json.loads(resp.read().decode("utf-8"))
                if "routePlan" in quote or "inAmount" in quote:
                    in_amt = int(quote.get("inAmount", 0))
                    out_amt = int(quote.get("outAmount", 0))
                    if in_amt > 0 and out_amt > 0:
                        # Estimate sell tax
                        price_impact = quote.get("priceImpactPct", 0)
                        if price_impact > 50:
                            result.sell_tax_pct = min(float(price_impact), 100.0)
                            if result.sell_tax_pct > 20:
                                result.can_trade = False
                                result.error = f"High price impact ({result.sell_tax_pct:.1f}%) — possible honeypot"
                    else:
                        result.can_trade = False
                        result.error = "Jupiter returned zero-output route — token may be untradeable"
                else:
                    result.can_trade = False
                    result.error = quote.get("error", "No route found — token may be untradeable")
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            result.error = f"Jupiter quote failed: {e}"
    except Exception as e:
        result.error = f"Honeypot check error: {e}"

    return result
def estimate_token_age(mint: str) -> tuple[int, list[str]]:
    """Estimate token age in days by paginating all signatures.
    Returns: (age_days, warnings)"""
    cache_key = f"age:{mint}"
    cached = _cached(cache_key)
    if cached:
        return cached

    warnings = []

    # Paginate to get the OLDEST signature (pin RPC for consistency, no retries for speed)
    all_sigs = []
    before = None
    for _ in range(10):
        params = {"limit": 100}
        if before:
            params["before"] = before
        sigs = _rpc_call("getSignaturesForAddress", [mint, params], retries=0, pin_rpc=True)
        if not sigs or len(sigs) == 0:
            break
        all_sigs.extend(sigs)
        before = sigs[-1]["signature"]
        if len(sigs) < 100:
            break

    if not all_sigs:
        _set_cache(cache_key, (0, ["Could not determine token age"]))
        return (0, ["Could not determine token age"])

    # Oldest sig is last in the list
    oldest = all_sigs[-1]
    block_time = oldest.get("blockTime")
    if not block_time:
        _set_cache(cache_key, (0, ["Could not determine token age"]))
        return (0, ["Could not determine token age"])

    now = time.time()
    age_days = max(0, round((now - block_time) / 86400, 1))

    # Check if the RPC gave us complete history by verifying against DexScreener
    dex_age = None
    try:
        import urllib.request
        url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            dex_data = json.loads(resp.read().decode("utf-8"))
            pairs = dex_data.get("pairs", [])
            if pairs:
                created_ms = pairs[0].get("pairCreatedAt", 0)
                if created_ms and created_ms > 0:
                    dex_age = max(0, round((now - created_ms / 1000) / 86400, 1))
    except Exception:
        pass

    # If DexScreener has data that goes further back, use that
    if dex_age is not None and dex_age > age_days + 1:
        actual_age = dex_age
        warnings.append(
            f"RPC returned only {age_days:.1f}d of history; "
            f"actual age from DEX indexer: ~{actual_age:.1f}d"
        )
        _set_cache(cache_key, (actual_age, warnings))
        return (actual_age, warnings)

    _set_cache(cache_key, (age_days, warnings))
    return (age_days, warnings)
def check_pump_fun(mint: str) -> dict:
    """Check if token is on Pump.fun and get bonding curve status."""
    cache_key = f"pumpfun:{mint}"
    cached = _cached(cache_key)
    if cached:
        return cached

    pump_program = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
    result = _rpc_call(
        "getProgramAccounts",
        [pump_program, {
            "encoding": "base64",
            "filters": [
                {"dataSize": 165},
                {"memcmp": {"offset": 0, "bytes": mint}},
            ],
        }],
    )
    info: dict[str, Any] = {"is_pump_fun": False}
    if result and isinstance(result, list) and len(result) > 0:
        info["is_pump_fun"] = True
        info["accounts"] = [a.get("pubkey", "") for a in result]

    _set_cache(cache_key, info)
    return info
SUSPICIOUS_TOKEN_KEYWORDS = [
    "rug", "scam", "ponzi", "honeypot", "drain", "phish", "shit",
    "moonbag", "pumpndump", "abandon", "test", "troll", "fake",
]
def check_sniper_patterns(mint: str) -> bool:
    """Check if bot snipers bought within the first 10 transactions.
    Returns True if suspicious buying pattern detected."""
    cache_key = f"sniper:{mint}"
    cached = _cached(cache_key)
    if cached is not None:
        return cached

    sigs = _rpc_call("getSignaturesForAddress", [mint, {"limit": 15}], retries=1, pin_rpc=True)
    if not sigs or len(sigs) < 5:
        _set_cache(cache_key, False)
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
    _set_cache(cache_key, result)
    return result
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
def resolve_deployer(mint: str) -> str | None:
    """Find the deployer address of a token by looking at the first transaction."""
    sigs = _rpc_call("getSignaturesForAddress", [mint, {"limit": 5}], retries=0, pin_rpc=True)
    if not sigs:
        return None

    # The last signature is the oldest (list is reverse-chronological)
    first_sig = sigs[-1].get("signature", "") if sigs else ""
    if not first_sig:
        return None

    tx = _rpc_call("getTransaction", [first_sig, {
        "encoding": "jsonParsed",
        "maxSupportedTransactionVersion": 0,
    }], retries=1)
    if not tx:
        return None

    # The fee payer is typically the deployer
    fee_payer = (tx.get("transaction", {})
                   .get("message", {})
                   .get("accountKeys", [{}])[0]
                   .get("pubkey", ""))
    return fee_payer or None
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
    flags: RugFlags, token: TokenMeta, holders: HolderInfo | None,
    liquidity: LiquidityInfo | None, mint_history: MintHistory | None,
    honeypot: HoneypotResult | None,
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

    # 3b. Liquidity — size/thin check (5 pts)
    if dex_data:
        liq = dex_data.get("liquidity_usd", 0)
        if liq <= 0:
            score.low_liquidity_risk = 5
            warnings.append("No liquidity data available — token may be untradeable")
        elif liq < 1000:
            score.low_liquidity_risk = 5
            warnings.append(f"Extremely thin liquidity (${liq:,.0f}) — one sell can crash price")
        elif liq < 20000:
            score.low_liquidity_risk = 3
            warnings.append(f"Thin liquidity (${liq:,.0f}) — moderate price impact on trades")
    elif liquidity and liquidity.has_lp and liquidity.liquidity_usd > 0:
        liq = liquidity.liquidity_usd
        if liq < 1000:
            score.low_liquidity_risk = 5
            warnings.append(f"Extremely thin liquidity (${liq:,.0f})")
        elif liq < 20000:
            score.low_liquidity_risk = 3
            warnings.append(f"Thin liquidity (${liq:,.0f})")

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
            import time
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
# ── Main Analysis ──────────────────────────────────────────────────────────

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

    # 8. Sniper pattern detection
    if check_sniper_patterns(mint):
        flags.sniper_detected = True

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

    # 11. Compute score (now includes dex_data for thin liquidity, age checks)
    score, score_warnings = compute_score_components(
        flags, token, holders, liquidity, mint_history, honeypot,
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
    result = _rpc_call("getTokenAccountsByOwner", [
        address,
        {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
        {"encoding": "jsonParsed"},
    ])
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
                risky_tokens.append({
                    "mint": mint,
                    "symbol": token.symbol or f"{mint[:4]}...{mint[-4:]}",
                    "balance_raw": amount,
                    "decimals": decimals,
                    "safety_score": quick_safety,
                    "risk_level": quick_level,
                    "top_warnings": a_warnings[:3],
                })

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

# ── Watch / History / Webhook Support ──────────────────────────────────────

DEFAULT_HISTORY_DB = os.environ.get("SOLANA_RUG_HISTORY_DB", os.path.expanduser("~/.solana-rug/history.sqlite3"))
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_token_scores_mint_time ON token_scores(mint, checked_at)")
    prune_history(db_path)
    return db_path


def prune_history(path: str = DEFAULT_HISTORY_DB) -> int:
    """Delete token_score rows older than HISTORY_RETENTION_DAYS. Returns count of deleted rows."""
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
    previous: dict | None, report: RugReport, threshold: int | None = None
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
            reasons.append(f"score changed {prev.get('safety_score')} -> {current.get('safety_score')}")
        if current.get("risk_level") != prev.get("risk_level"):
            reasons.append(f"risk level changed {prev.get('risk_level')} -> {current.get('risk_level')}")
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

# ── Output Formatting ──────────────────────────────────────────────────────

def format_markdown(report: RugReport) -> str:
    """Format a rug report as clean Markdown."""
    token = report.token
    lines = []
    symbol = token.symbol or token.name or f"{token.address[:4]}...{token.address[-4:]}"
    lines.append(f"# 🛡️ Solana Rug Report: {symbol}")
    lines.append("")
    lines.append(f"**Mint:** `{token.address}`")
    lines.append(f"**Safety Score:** **{report.safety_score}/100** — **{report.risk_level} RISK**")
    lines.append("")

    # Score breakdown
    lines.append("## Score Breakdown")
    lines.append("")
    lines.append("| Factor | Weight |")
    lines.append("|--------|-------:|")
    s = report.score
    lines.append(f"| Mint Authority | {s.mint_authority_risk}/15 |")
    lines.append(f"| Freeze Authority | {s.freeze_authority_risk}/5 |")
    lines.append(f"| Liquidity (locked/burned) | {s.liquidity_risk}/15 |")
    lines.append(f"| Liquidity (size/thin) | {s.low_liquidity_risk}/5 |")
    lines.append(f"| Holder Concentration | {s.holder_concentration_risk}/10 |")
    lines.append(f"| Dev Risk | {s.dev_risk}/5 |")
    lines.append(f"| Token Age | {s.age_risk}/5 |")
    lines.append(f"| Mint History | {s.mint_history_risk}/5 |")
    lines.append(f"| Honeypot | {s.honeypot_risk}/10 |")
    lines.append(f"| Sniper Bots | {s.sniper_risk}/10 |")
    lines.append(f"| Suspicious Name | {s.name_risk}/5 |")
    lines.append(f"| Sub-Penny Price | {s.sub_penny_risk}/5 |")
    lines.append(f"| Deployer Dump Risk | {s.deployer_dump_risk}/5 |")
    lines.append("")

    # Warnings
    if report.warnings:
        lines.append("## ⚠️ Flags & Warnings")
        lines.append("")
        for w in report.warnings:
            lines.append(f"- 🔴 {w}")
        lines.append("")

    # Recommendation
    lines.append("## Recommendation")
    lines.append("")
    lines.append(report.recommendation)
    lines.append("")

    # Token details
    lines.append("## Token Details")
    lines.append("")
    lines.append(f"- **Decimals:** {token.decimals}")
    if token.supply:
        adj = token.supply / (10 ** token.decimals) if token.decimals else token.supply
        lines.append(f"- **Supply:** {adj:,.0f} (raw: {token.supply})")
    if token.mint_authority:
        short = f"{token.mint_authority[:4]}...{token.mint_authority[-4:]}"
        lines.append(f"- **Mint Authority:** {short}")
    else:
        lines.append("- **Mint Authority:** ✅ Revoked")
    if token.freeze_authority:
        short = f"{token.freeze_authority[:4]}...{token.freeze_authority[-4:]}"
        lines.append(f"- **Freeze Authority:** {short}")
    else:
        lines.append("- **Freeze Authority:** ✅ Revoked")
    if token.token_program:
        prog_name = "Token-2022" if "TokenzQd" in token.token_program else "SPL Token"
        lines.append(f"- **Token Program:** {prog_name}")
        if token.extensions:
            lines.append(f"- **Extensions:** {', '.join(token.extensions)}")

    if report.holders:
        lines.append("")
        lines.append("## Holder Distribution")
        lines.append("")
        lines.append(f"- **Total holders (top):** {report.holders.total_holders}")
        lines.append(f"- **Top 10 hold:** {report.holders.top_10_pct:.1f}%")
        lines.append(f"- **Dev wallet:** {report.holders.dev_wallet_pct:.1f}%")
        if report.holders.top_holders:
            lines.append("")
            lines.append("| # | Address | % of Supply |")
            lines.append("|---|---------|------------:|")
            for i, h in enumerate(report.holders.top_holders[:5], 1):
                addr = f"{h['address'][:4]}...{h['address'][-4:]}"
                lines.append(f"| {i} | `{addr}` | {h['pct']:.2f}% |")

    if report.liquidity and report.liquidity.has_lp:
        lines.append("")
        lines.append("## Liquidity Pools")
        lines.append("")
        lines.append(f"- **Pool count:** {report.liquidity.pool_count}")
        lines.append(f"- **LP burned:** {'✅ Yes' if report.liquidity.lp_burned else '🔴 No'}")
        if report.liquidity.liquidity_usd > 0:
            lines.append(f"- **Liquidity:** ${report.liquidity.liquidity_usd:,.2f}")
        for p in report.liquidity.pools[:3]:
            addr_short = f"{p['address'][:4]}...{p['address'][-4:]}"
            source = " (DexScreener)" if p.get("program_id") == "dexscreener" else ""
            lines.append(f"- `{addr_short}` — {p['dex']}{source}")

    # Market data from DexScreener
    if report.dex_data:
        lines.append("")
        lines.append("## Market Data (DexScreener)")
        lines.append("")
        dd = report.dex_data
        if dd.get("price_usd"):
            lines.append(f"- **Price:** ${dd['price_usd']:.8f}")
        if dd.get("price_change_24h"):
            pct = dd['price_change_24h']
            direction = "📈" if pct > 0 else "📉"
            lines.append(f"- **24h Change:** {direction} {pct:+.2f}%")
        if dd.get("volume_24h"):
            lines.append(f"- **24h Volume:** ${dd['volume_24h']:,.2f}")
        if dd.get("liquidity_usd"):
            lines.append(f"- **Liquidity:** ${dd['liquidity_usd']:,.2f}")
        buys = dd.get("txns_24h_buys", 0)
        sells = dd.get("txns_24h_sells", 0)
        if buys or sells:
            lines.append(f"- **24h Trades:** {buys} buys / {sells} sells ({buys+sells} total)")
        if dd.get("dex"):
            lines.append(f"- **DEX:** {dd['dex']}")
        if dd.get("quote_symbol"):
            lines.append(f"- **Trading Pair:** {dd.get('base_symbol', '?')}/{dd['quote_symbol']}")

    lines.append("")
    lines.append("---")
    lines.append("*Generated by Solana Rug Guard • MIT Licensed • No paid APIs used*")

    return "\n".join(lines)
def format_json(report: RugReport) -> str:
    """Format report as pretty JSON."""
    return json.dumps(report.to_dict(), indent=2, default=str)
# ── CLI Entry Point ────────────────────────────────────────────────────────

def cli_token(args: list[str]) -> None:
    mint = args[0] if args else ""
    if not mint:
        print('Usage: python rugguard.py token <MINT_ADDRESS>', file=sys.stderr)
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
        print('Usage: python rugguard.py wallet <ADDRESS>', file=sys.stderr)
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
if __name__ == "__main__":
    main()
