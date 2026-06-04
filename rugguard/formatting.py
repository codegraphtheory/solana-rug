#!/usr/bin/env python3
"""rugguard/formatting.py — Output formatting for Solana Rug Guard.

Extracted from scripts/rugguard.py. Contains all formatting and output
functions for markdown, JSON, CSV, JSONL, SVG badges, comparison tables,
and timeline rendering.

MIT License -- free, open-source, no paid APIs required.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .analysis import RugReport
from .rpc import _rpc_call


def _sparkline_from_change(pct_change: float) -> str | None:
    """Build an ASCII sparkline from a 24h price change percentage.

    Since DexScreener only gives one price point and its 24h change, we
    interpolate a 10-character sparkline that approximates the price
    trajectory: the start is derived from the change, the middle is a
    gentle curve toward the end, and the end is the current price level.

    Uses Unicode block chars.
    Returns None when pct_change is 0 or unavailable (flat/no trend).
    """
    if pct_change is None or pct_change == 0:
        return None

    blocks = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"]
    n = 10

    if pct_change > 0:
        # Bullish: upward curve from -pct/2 to +pct/2
        values = [-abs(pct_change) * 0.3 + (abs(pct_change) * 0.6) * (i / (n - 1)) for i in range(n)]
    else:
        # Bearish: downward curve from +pct/2 to -pct/2
        values = [abs(pct_change) * 0.3 - (abs(pct_change) * 0.6) * (i / (n - 1)) for i in range(n)]

    min_v = min(values)
    max_v = max(values)
    if max_v == min_v:
        return None

    spark = []
    for v in values:
        idx = int((v - min_v) / (max_v - min_v) * (len(blocks) - 1))
        idx = max(0, min(idx, len(blocks) - 1))
        spark.append(blocks[idx])

    color = "\U0001f7e2" if pct_change > 0 else "\U0001f534"  # green/red circle
    return color + "".join(spark) if abs(pct_change) > 1 else "".join(spark)


def format_markdown(report: RugReport) -> str:
    """Format a rug report as clean Markdown."""
    token = report.token
    lines = []
    symbol = token.symbol or token.name or f"{token.address[:4]}...{token.address[-4:]}"
    lines.append(f"# 🛡️ Solana Rug Report: {symbol}")
    lines.append("")
    lines.append(f"**Mint:** `{token.address}`")
    lines.append(f"**Safety Score:** **{report.safety_score}/100** -- **{report.risk_level} RISK**")
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
            lines.append(f"- `{addr_short}` -- {p['dex']}{source}")

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
        # ASCII price sparkline
        spark = _sparkline_from_change(dd.get("price_change_24h", 0))
        if spark:
            lines.append(f"- **24h Sparkline:** {spark}")
        if dd.get("dex"):
            lines.append(f"- **DEX:** {dd['dex']}")
        if dd.get("quote_symbol"):
            lines.append(f"- **Trading Pair:** {dd.get('base_symbol', '?')}/{dd['quote_symbol']}")

    lines.append("")
    lines.append("---")
    lines.append("*Generated by Solana Rug Guard - MIT Licensed - No paid APIs used*")

    return "\n".join(lines)


def format_json(report: RugReport) -> str:
    """Format report as pretty JSON."""
    return json.dumps(report.to_dict(), indent=2, default=str)


def _svg_badge(report: RugReport, style: str = "flat", label: str = "safety") -> str:
    """Generate a shields.io-compatible SVG badge."""
    score = report.safety_score
    level = report.risk_level
    if score >= 70:
        bg = "#4c1"
    elif score >= 40:
        bg = "#e67e22"
    elif score >= 20:
        bg = "#e74c3c"
    else:
        bg = "#c0392b"

    label_text = label
    value_text = str(score) + "/100 - " + level
    label_w = max(len(label_text) * 7 + 10, 40)
    value_w = len(value_text) * 7 + 10
    total_w = label_w + value_w
    h = 20
    rx = 3 if style == "flat" else 0
    lx = label_w // 2
    vx = label_w + value_w // 2

    lines = []
    lines.append('<svg xmlns="http://www.w3.org/2000/svg" width="' + str(total_w) + '" height="' + str(h) + '">')
    lines.append('<linearGradient id="l" x2="0" y2="1">'
                 '<stop offset="0%" stop-color="#bbb" stop-opacity=".1"/>'
                 '<stop offset="100%" stop-color="#000" stop-opacity=".1"/>'
                 '</linearGradient>')
    lines.append('<rect width="' + str(label_w) + '" height="' + str(h) + '" fill="#555" rx="' + str(rx) + '"/>')
    lines.append('<rect x="' + str(label_w) + '" width="' + str(value_w)
                 + '" height="' + str(h) + '" fill="' + bg + '" rx="' + str(rx) + '"/>')
    lines.append('<rect width="' + str(total_w) + '" height="' + str(h) + '" fill="url(#l)"/>')
    lines.append('<g fill="#fff" font-family="Arial,sans-serif" font-size="11" text-anchor="middle">')
    lines.append('<text x="' + str(lx) + '" y="14">' + _escape_svg(label_text) + '</text>')
    lines.append('<text x="' + str(vx) + '" y="14">' + _escape_svg(value_text) + '</text>')
    lines.append('</g></svg>')
    return "\n".join(lines)


def _escape_svg(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _report_csv_rows(report: RugReport) -> list[dict]:
    """Build a list of flat dicts (one per token) for CSV/JSONL export from a token report."""
    d = report.to_dict()
    flat: dict[str, Any] = {}
    flat["token_address"] = report.token.address
    flat["token_symbol"] = report.token.symbol
    flat["token_name"] = report.token.name
    flat["token_decimals"] = report.token.decimals
    flat["safety_score"] = report.safety_score
    flat["risk_level"] = report.risk_level
    flat["recommendation"] = report.recommendation
    flat["warnings"] = "; ".join(report.warnings)
    # Score breakdown
    score = d.get("score", {})
    for k, v in score.items():
        flat[f"score_{k}"] = v
    # Flags
    flags = d.get("flags", {})
    for k, v in flags.items():
        flat[f"flag_{k}"] = int(bool(v))
    # Market data
    market = d.get("market_data", {})
    for k, v in market.items():
        flat[f"market_{k}"] = v if v is not None else ""
    return [flat]


def _wallet_csv_rows(wallet_result: dict) -> list[dict]:
    """Build a list of flat dicts (one per risky token) for CSV/JSONL export from a wallet scan."""
    rows: list[dict] = []
    base: dict[str, Any] = {
        "wallet_address": wallet_result.get("address", ""),
        "total_tokens": wallet_result.get("total_tokens", 0),
        "risky_count": wallet_result.get("risky_count", 0),
        "summary": wallet_result.get("summary", ""),
    }
    risky = wallet_result.get("risky_tokens", [])
    if not risky:
        rows.append(base)
    else:
        for t in risky:
            row = dict(base)
            row["token_mint"] = t.get("mint", "")
            row["token_symbol"] = t.get("symbol", "")
            row["balance_raw"] = t.get("balance_raw", 0)
            row["token_decimals"] = t.get("decimals", 0)
            row["safety_score"] = t.get("safety_score", 0)
            row["risk_level"] = t.get("risk_level", "")
            row["top_warnings"] = "; ".join(t.get("top_warnings", []))
            rows.append(row)
    return rows


def format_csv(rows: list[dict]) -> str:
    """Format a list of flat dicts as CSV string."""
    import csv as _csv
    import io
    if not rows:
        return ""
    buf = io.StringIO()
    writer = _csv.DictWriter(buf, fieldnames=list(rows[0].keys()), quoting=_csv.QUOTE_MINIMAL)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: v if v is not None else "" for k, v in row.items()})
    return buf.getvalue()


def format_jsonl(rows: list[dict]) -> str:
    """Format a list of flat dicts as JSONL (one JSON object per line)."""
    lines_list = [json.dumps(row, default=str) for row in rows]
    return "\n".join(lines_list) + "\n" if lines_list else ""


# ── Comparison Table ──────────────────────────────────────────────────────


def _format_comparison_table(reports: list[RugReport],
                             sort_by: str = "score") -> str:
    """Render a side-by-side ASCII comparison table for multiple tokens.

    Each column = one token, auto-sized to widest value.
    Tokens are sorted by safety_score ascending (riskiest first).
    """
    if not reports:
        return ""

    # Sort: score asc (riskiest first)
    def _sort_key_score(r: RugReport) -> int:
        return r.safety_score

    def _sort_key_name(r: RugReport) -> str:
        return r.token.name or r.token.symbol or r.token.address

    def _sort_key_age(r: RugReport) -> int:
        return -r.score.age_risk

    def _sort_key_liquidity(r: RugReport) -> float:
        return -(r.dex_data.get("liquidity_usd", 0) if r.dex_data else 0)

    if sort_by == "score":
        key_fn = _sort_key_score
    elif sort_by == "name":
        key_fn = _sort_key_name
    elif sort_by == "age":
        key_fn = _sort_key_age
    elif sort_by == "liquidity":
        key_fn = _sort_key_liquidity
    else:
        key_fn = _sort_key_score
    sorted_reports = sorted(reports, key=key_fn)

    # Build rows: each is a list of values, one per token
    headers = ["Metric"]
    for r in sorted_reports:
        sym = r.token.symbol or r.token.name or r.token.address[:8]
        headers.append(sym)

    rows: list[list[str]] = [headers]

    def val(name: str, vals: list[str]) -> None:
        rows.append([name] + vals)

    val("Safety Score", [str(r.safety_score) for r in sorted_reports])
    val("Risk Level", [r.risk_level for r in sorted_reports])

    prices = []
    for r in sorted_reports:
        if r.dex_data and r.dex_data.get("price_usd"):
            p = r.dex_data["price_usd"]
            prices.append(f"${p:.8f}" if p < 1 else f"${p:.4f}")
        else:
            prices.append("-")
    val("Price", prices)

    changes = []
    for r in sorted_reports:
        if r.dex_data and r.dex_data.get("price_change_24h"):
            pct = r.dex_data["price_change_24h"]
            changes.append(f"{pct:+.2f}%")
        else:
            changes.append("-")
    val("24h Change", changes)

    liqs = []
    for r in sorted_reports:
        if r.dex_data and r.dex_data.get("liquidity_usd"):
            liqs.append(f"${r.dex_data['liquidity_usd']:,.0f}")
        else:
            liqs.append("-")
    val("Liquidity", liqs)

    vols = []
    for r in sorted_reports:
        if r.dex_data and r.dex_data.get("volume_24h"):
            vols.append(f"${r.dex_data['volume_24h']:,.0f}")
        else:
            vols.append("-")
    val("Volume 24h", vols)

    hldrs = []
    for r in sorted_reports:
        if r.holders:
            hldrs.append(str(r.holders.total_holders))
        else:
            hldrs.append("-")
    val("Holders", hldrs)

    top10 = []
    for r in sorted_reports:
        if r.holders:
            top10.append(f"{r.holders.top_10_pct:.1f}%")
        else:
            top10.append("-")
    val("Top 10%", top10)

    wcounts = [str(len(r.warnings)) for r in sorted_reports]
    val("Warnings", wcounts)

    col_widths: list[int] = []
    for ci in range(len(rows[0])):
        col_widths.append(max(len(r[ci]) for r in rows))
    col_widths[0] = max(col_widths[0], 12)

    sep = " | "
    lines = []
    hdr_parts = [h.ljust(col_widths[i]) for i, h in enumerate(rows[0])]
    lines.append(sep.join(hdr_parts))
    sep_parts = ["-" * col_widths[i] for i in range(len(col_widths))]
    lines.append(sep.join(sep_parts))
    for r in rows[1:]:
        parts = [r[i].ljust(col_widths[i]) for i in range(len(r))]
        lines.append(sep.join(parts))

    return "\n".join(lines)


# ── Timeline ──────────────────────────────────────────────────────────────


def _fetch_timeline_events(mint: str) -> list[dict]:
    """Fetch chronological events for a token mint address.

    Fetches up to 100 signatures and classifies each transaction.
    Returns list of dicts with: time, rel_time, event, tx_sig, details
    """
    events = []

    # Fetch signatures
    sigs = _rpc_call("getSignaturesForAddress", [mint, {"limit": 100}])
    if not sigs:
        return events

    # Use first sig time as T0
    t0 = None
    for s in sigs:
        bt = s.get("blockTime")
        if bt:
            t0 = bt
            break

    if not t0:
        # Fallback: use earliest sig
        t0 = sigs[-1].get("blockTime", time.time())

    for sig_info in sigs:
        tx_sig = sig_info.get("signature", "")
        bt = sig_info.get("blockTime", 0)
        if not tx_sig or not bt:
            continue

        rel_time = bt - t0
        if rel_time < 0:
            rel_time = 0

        # Format relative time
        if rel_time < 60:
            rel_str = f"T+{rel_time}s"
        elif rel_time < 3600:
            rel_str = f"T+{rel_time // 60}m"
        elif rel_time < 86400:
            rel_str = f"T+{rel_time // 3600}h"
        else:
            rel_str = f"+{rel_time // 86400}d"

        # Fetch transaction details
        tx = _rpc_call("getTransaction", [tx_sig, {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}])
        if not tx:
            events.append({
                "time": bt,
                "rel_time": rel_str,
                "event": "Transaction",
                "tx_sig": tx_sig[:16] + "...",
                "details": "",
                "suspicious": False,
            })
            continue

        meta = tx.get("meta", {})
        if meta and meta.get("err"):
            events.append({
                "time": bt,
                "rel_time": rel_str,
                "event": "Failed Transaction",
                "tx_sig": tx_sig[:16] + "...",
                "details": str(meta.get("err", ""))[:80],
                "suspicious": False,
            })
            continue

        # Check instructions for classification
        tx_data = tx.get("transaction", {})
        msg = tx_data.get("message", {})
        instructions = msg.get("instructions", [])

        event_type = "Transaction"
        details = ""
        suspicious = rel_time < 3  # within 3s = sniper

        for ix in instructions:
            parsed = ix.get("parsed", {})

            if "initializeMint" in str(ix) or "InitializeMint" in str(ix):
                event_type = "Token Created"
                suspicious = False
                break
            if "setAuthority" in str(ix) or "SetAuthority" in str(ix):
                auth_info = parsed.get("info", {})
                auth_type = auth_info.get("authorityType", "")
                new_auth = auth_info.get("newAuthority", "none")
                event_type = f"Authority Change ({auth_type})"
                details = f"New: {new_auth[:8]}..." if new_auth != "none" else "Revoked"
                if "revoke" in str(ix).lower() or new_auth == "none":
                    suspicious = False
                else:
                    suspicious = True
                break
            if "initializeAccount" in str(ix).lower():
                continue  # noise
            if "transfer" in str(ix).lower() or "Transfer" in str(ix):
                # Check if large transfer
                try:
                    amt = int(parsed.get("info", {}).get("amount", "0"))
                except (ValueError, TypeError):
                    amt = 0
                if amt > 1_000_000_000_000:  # > 1M tokens (rough)
                    event_type = "Large Transfer"
                    suspicious = True
                else:
                    event_type = "Transfer"
                break

        events.append({
            "time": bt,
            "rel_time": rel_str,
            "event": event_type,
            "tx_sig": tx_sig[:16] + "...",
            "details": details,
            "suspicious": suspicious,
        })

    # Sort chronologically
    events.sort(key=lambda e: e["time"])
    return events


def _format_timeline(mint: str, events: list[dict]) -> str:
    """Format timeline events as human-readable output."""
    if not events:
        return f"No events found for {mint[:8]}..."

    lines = [f"# Timeline for {mint[:8]}..."]
    lines.append("")

    for e in events:
        marker = "⚠️ " if e["suspicious"] else "  "
        detail = f" -- {e['details']}" if e["details"] else ""
        lines.append(f"{marker}{e['rel_time']}: {e['event']}{detail}")
        lines.append(f"   Tx: {e['tx_sig']}")

    return "\n".join(lines)


def _format_timeline_json(events: list[dict]) -> str:
    """Format timeline events as JSON."""
    clean = [{"rel_time": e["rel_time"], "event": e["event"],
              "tx_sig": e["tx_sig"], "details": e["details"],
              "suspicious": e["suspicious"]} for e in events]
    return json.dumps(clean, indent=2)
