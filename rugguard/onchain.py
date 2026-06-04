#!/usr/bin/env python3
"""rugguard/onchain.py — On-chain data fetching functions for Solana Rug Guard.

Extracted from scripts/rugguard.py. Contains all functions that interact
with the Solana blockchain via RPC or external APIs (DexScreener, Jupiter).

MIT License — free, open-source, no paid APIs required.
"""

from __future__ import annotations

import json
import time
import urllib.request
from base64 import b64decode
from dataclasses import asdict, dataclass, field
from typing import Any

from .rpc import (
    _cached,
    _rpc_call,
    _set_cache,
)

# ── Constants ──────────────────────────────────────────────────────────────────

_TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# ── Data Models ────────────────────────────────────────────────────────────────


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


# ── DexScreener Helpers ─────────────────────────────────────────────────────────

_DEX_SCREENER_URL = "https://api.dexscreener.com/latest/dex/tokens/"


def _dex_screener_fetch(mint: str) -> dict | None:
    """Fetch token data from DexScreener API. Returns first pair or None."""
    cache_key = f"dexscreener:{mint}"
    cached = _cached(cache_key)
    if cached:
        return cached
    try:
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


# ── On-Chain Data Fetching Functions ────────────────────────────────────────────


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
        # Raw base64 data -- no jsonParsed available
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

    # getTokenLargestAccounts failed -- try getProgramAccounts (for Token-2022)
    # Filter by mint using memcmp on the account data at offset 0
    gpa = _rpc_call("getProgramAccounts", [
        _TOKEN_2022_PROGRAM,
        {
            "encoding": "jsonParsed",
            "filters": [
                {"memcmp": {"offset": 0, "bytes": mint}},
                {"dataSize": 165},  # Token-2022 account size
            ],
        },
    ], retries=0, pin_rpc=False)
    if gpa and isinstance(gpa, list) and len(gpa) > 0:
        accounts = []
        for item in gpa:
            acct = item.get("account", {})
            data = acct.get("data", {})
            parsed = data.get("parsed", {}) if isinstance(data, dict) else {}
            info = parsed.get("info", {})
            if info.get("mint") == mint:
                amt = int(info.get("tokenAmount", {}).get("amount", "0"))
                owner = info.get("owner", "")
                if amt > 0:
                    accounts.append({"address": owner, "amount": amt})
        if accounts:
            total_supply = sum(a["amount"] for a in accounts)
            accounts.sort(key=lambda a: a["amount"], reverse=True)
            top_holders = []
            pct_sum = 0.0
            for a in accounts[:20]:
                pct = round(a["amount"] / total_supply * 100, 2) if total_supply > 0 else 0
                pct_sum += pct
                top_holders.append({"address": a["address"], "amount": a["amount"], "pct": pct})
            dev_pct = top_holders[0]["pct"] if top_holders else 0.0
            info = HolderInfo(
                total_holders=len(accounts),
                top_10_pct=min(pct_sum, 100.0),
                dev_wallet_pct=dev_pct,
                top_holders=top_holders[:10],
            )
            _set_cache(cache_key, asdict(info))
            return info

    # RPC failed (common for Token-2022 on public RPC) -- try DexScreener
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
            # Known DEXes lock LP by design -- mark as burned
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
    return pool_address  # Simplified -- in production we'd parse the account data


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
                                result.error = f"High price impact ({result.sell_tax_pct:.1f}%) -- possible honeypot"
                    else:
                        result.can_trade = False
                        result.error = "Jupiter returned zero-output route -- token may be untradeable"
                else:
                    result.can_trade = False
                    result.error = quote.get("error", "No route found -- token may be untradeable")
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
