from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

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
