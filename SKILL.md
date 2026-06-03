---
name: solana-rug
description: "On-chain rug-pull detection for Solana tokens and wallets. Safety Score 0-100. Checks mint/freeze authority, LP pools, holder concentration, Token-2022 extensions, sniping patterns, suspicious names, sub-penny prices, deployer dump risk. No paid APIs required."
version: 1.4.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [solana, blockchain, crypto, rug-check, security, defi, token-analysis]
    related_skills: [blockchain/solana]
---

# Solana Rug Guard — Hermes Agent Skill

**On-chain rug-pull detection engine for Solana tokens and wallets.**

Checks 13 risk factors across 4 data sources:
- **On-chain RPC** — mint/freeze authority, token program, account data size
- **DexScreener API** — LP pools, price, volume, liquidity, age, trading pair
- **Transaction patterns** — sniper detection, mint history, deployer activity
- **Heuristics** — suspicious name keywords, sub-penny price, thin liquidity

No API keys required. Falls back gracefully when public RPC is rate-limited.

---

## When to Use

Load this skill when the user asks ANY of:
- "Is token `<ADDRESS>` safe?"
- "Rug-check `<MINT>`"
- "Analyze `<ADDRESS>` for scams / rugs"
- "What's the safety score of `<TOKEN>`?"
- "Is `<TOKEN>` a honeypot?"
- "Scan wallet `<ADDRESS>` for risky tokens"
- Any question about a Solana token's legitimacy

---

## Installation

```bash
# From Hermes official skills (after PR merges):
hermes skills install official/blockchain/solana-rug

# From GitHub tap:
hermes skills tap add graphtheory/solana-rug

# Direct from source (Hermes Agent repo):
cd optional-skills/blockchain/solana-rug/
hermes skills install ./SKILL.md
```

---

## How to Run

```bash
# Path inside the installed skill:
SKILL_DIR=~/.hermes/skills/blockchain/solana-rug/scripts

# Token analysis (JSON default):
python3 $SKILL_DIR/rugguard.py token <MINT_ADDRESS>

# Human-readable Markdown report:
python3 $SKILL_DIR/rugguard.py token <MINT_ADDRESS> --md

# Batch scan a wallet for risky tokens:
python3 $SKILL_DIR/rugguard.py wallet <WALLET_ADDRESS>

# Help:
python3 $SKILL_DIR/rugguard.py --help
```

The Hermes agent should always use `--md` for human consumption and `--json` for programmatic use.

---

## Output — Safety Score Breakdown

The score is **0–100** (higher = safer). **13 risk factors** are scored independently:

| Factor | Max | What It Detects | Data Source |
|--------|:---:|-----------------|-------------|
| Mint Authority | 15 | Dev can still mint unlimited tokens | RPC |
| Freeze Authority | 5 | Dev can freeze accounts | RPC |
| Liquidity (locked/burned) | 15 | LP tokens not burned, pool missing | RPC + DexScreener |
| Liquidity (size/thin) | 5 | Pool under $20k — high price impact | DexScreener |
| Holder Concentration | 10 | Top 10 wallets own >50% of supply | RPC + DexScreener |
| Dev Risk | 5 | Dev holds >15% of supply | RPC |
| Token Age | 5 | Under 7 days old — statistically riskier | DexScreener |
| Mint History | 5 | Dev minted more tokens after launch | RPC |
| Honeypot | 10 | Sell simulation failed | Jupiter API |
| **Sniper Bots** | **10** | Bots bought within first 20s of launch | RPC sigs |
| **Suspicious Name** | **5** | Name contains "rug", "scam", "ponzi", etc. | On-chain + DexScreener |
| **Sub-Penny Price** | **5** | Price < $0.0001 — typical of dead tokens | DexScreener |
| **Deployer Dump Risk** | **5** | Dev could crash price by selling | DexScreener + RPC |

Score interpretation:
- **80–100**: LOW — Standard risks. The on-chain mechanics are clean.
- **50–79**: MEDIUM — Some risk factors present. Review flagged warnings.
- **20–49**: HIGH — Multiple red flags. Likely a risky token.
- **0–19**: CRITICAL — Strong evidence of malicious setup.

---

## Output — Example JSON

```json
{
  "token": {
    "address": "F4J5LKyEQraMem8nspPAzwHXaaKMMDsxyt7GUK94pump",
    "symbol": "RUG",
    "decimals": 6,
    "supply": 999999927698532,
    "mint_authority": null,
    "freeze_authority": null,
    "token_program": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "extensions": ["metadataPointer", "tokenMetadata"]
  },
  "safety_score": 79,
  "risk_level": "LOW",
  "flags": {
    "mint_authority_active": false,
    "freeze_authority_active": false,
    "sniper_detected": false,
    "suspicious_name": true,
    "sub_penny_price": true,
    "deployer_can_crash_price": true
  },
  "warnings": [
    "Thin liquidity ($6,811) — moderate price impact",
    "Suspicious token name detected",
    "Sub-penny price — typical of dead tokens",
    "Deployer holds significant supply"
  ],
  "market_data": {
    "dex": "pumpswap",
    "liquidity_usd": 6929.29,
    "volume_24h": 16583.86,
    "price_usd": 0.00000956,
    "price_change_24h": 8.79,
    "txns_24h": 402
  }
}
```

---

## Output — Markdown Sections

The `--md` output includes:
1. **Header** — mint, safety score, risk level
2. **Score Breakdown** — all 13 risk factors with their scores
3. **Flags & Warnings** — every issue detected (red bullet list)
4. **Recommendation** — plain-English summary
5. **Token Details** — decimals, supply, authorities, program, extensions
6. **Holder Distribution** — total holders, top 10%, dev wallet %
7. **Liquidity Pools** — pool count, LP burned status, liquidity $, DEX name
8. **Market Data** — price, 24h change, volume, liquidity, trade counts, pair

---

## 13 Risk Checks — Detailed Documentation

### 1. Mint Authority (15 pts)
Calls `getAccountInfo` on the mint. If `mintAuthority` is non-null, the dev can print unlimited new tokens.

### 2. Freeze Authority (5 pts)
Same account info. If `freezeAuthority` is non-null, the dev can freeze any holder's tokens.

### 3. Liquidity Locked/Burned (15 pts)
Searches Raydium AMM, Raydium CPMM, pumpSwap, and Orca via `getProgramAccounts`. Falls back to DexScreener API. Pump.fun/pumpSwap pools are assumed locked (bonding curve design).

### 4. Liquidity Size/Thin (5 pts)
Uses DexScreener liquidity USD. Flags at thresholds: <$1k (5pts), <$20k (3pts).

### 5. Holder Concentration (10 pts)
`getTokenLargestAccounts` via RPC. Falls back to DexScreener tx estimates for Token-2022. Flags: >90% (15pts), >70% (12pts), >50% (8pts). Also flags low holder count (<10 = +5pts, <50 = +3pts).

### 6. Dev Risk (5 pts)
First holder's % of supply. >30% (10pts), >15% (5pts).

### 7. Token Age (5 pts)
Paginates all mint signatures (pinned to one RPC node). Falls back to DexScreener `pairCreatedAt` when RPC history is truncated. <7 days = 3pts.

### 8. Mint History (5 pts)
Scans recent transactions to detect tokens minted to the deployer after launch.

### 9. Honeypot (10 pts)
Jupiter quote API simulates a 0.01 SOL sell. If no route found or price impact >50%, flags as honeypot.

### 10. Sniper Bots (10 pts)
Reads the first 15 mint signatures and counts rapid buys (transactions within 50 slots of each other). 3+ rapid buys = sniping detected.

### 11. Suspicious Name (5 pts)
Checks on-chain name/symbol + DexScreener pair symbol against keyword blacklist: `rug`, `scam`, `ponzi`, `honeypot`, `drain`, `phish`, `shit`, `moonbag`, `pumpndump`, `abandon`, `test`, `troll`, `fake`.

### 12. Sub-Penny Price (5 pts)
If DexScreener price < $0.0001, flags the token. Sub-penny tokens statistically have near-zero organic demand.

### 13. Deployer Dump Risk (5 pts)
Calculates deployer's holdings as % of pool liquidity. If deployer's bag is worth >50% of the pool or they hold >10% of supply, the token is at risk of a crash sell.

---

## Wallet Scan

```bash
python3 $SKILL_DIR/rugguard.py wallet <ADDRESS>
```

Scans every SPL token held by a wallet. For each token with meaningful balance, checks mint authority. Returns prioritized list of risky tokens. This is a light scan (metadata + authorities only, not full analysis) to avoid excessive RPC calls.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SOLANA_RPC_URL` | `api.mainnet-beta.solana.com` | Override RPC endpoint. Use a private node (Helius, QuickNode) for production reliability |

---

## Known Limitations / Pitfalls

1. **Public RPC rate limits.** `getProgramAccounts` is often blocked. LP detection falls back to DexScreener which works reliably.
2. **Signature history truncated.** Public RPCs only keep ~12-24h of signatures for mint addresses. Age falls back to DexScreener `pairCreatedAt` when RPC data is insufficient.
3. **Token-2022 holder data.** `getTokenLargestAccounts` may return empty for Token-2022 tokens on public RPC. Falls back to DexScreener tx-count estimates.
4. **Jupiter API DNS issues.** Some environments block `jup.ag`. Honeypot check degrades gracefully if unreachable.
5. **Sniper detection needs 5+ mint signatures.** If the RPC has few sigs for the mint, sniper check returns false even if sniping happened (it happened on the DEX program, not the mint address).
6. **DexScreener rate-limited.** ~30 req/min free tier. Cached for 5 minutes.

---

## Verification Test

```bash
python3 $SKILL_DIR/rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --md
```

Expected: BONK returns safety score 85-100 (established token, authorities revoked, deep liquidity). Verifies the tool works end-to-end.

---

## Related

- `blockchain/solana` — Base Solana skill (wallet, balance, NFT, stats)
- Standalone PyPI: `pip install solana-rug`
