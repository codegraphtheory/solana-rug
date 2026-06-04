from __future__ import annotations

import json

from analysis import RugReport


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
        adj = token.supply / (10**token.decimals) if token.decimals else token.supply
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
            pct = dd["price_change_24h"]
            direction = "📈" if pct > 0 else "📉"
            lines.append(f"- **24h Change:** {direction} {pct:+.2f}%")
        if dd.get("volume_24h"):
            lines.append(f"- **24h Volume:** ${dd['volume_24h']:,.2f}")
        if dd.get("liquidity_usd"):
            lines.append(f"- **Liquidity:** ${dd['liquidity_usd']:,.2f}")
        buys = dd.get("txns_24h_buys", 0)
        sells = dd.get("txns_24h_sells", 0)
        if buys or sells:
            lines.append(f"- **24h Trades:** {buys} buys / {sells} sells ({buys + sells} total)")
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
