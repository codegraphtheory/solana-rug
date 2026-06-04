# Solana Rug Guard

[![CI](https://github.com/rugpullnet/solana-rug/actions/workflows/ci.yml/badge.svg)](https://github.com/rugpullnet/solana-rug/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**13-factor on-chain rug-pull detection for Solana tokens and wallets. No paid APIs. No registration. Just a Python script and a Hermes skill.**

Run it as a one-shot CLI against any mint or wallet. Or install it as a Hermes Agent skill and ask in natural language: *"Hey Hermes, is this token safe?"* Every check is deterministic — the same input always produces the same score, with a full breakdown of why.

---

## Install & Get Started

### Prerequisites

- Python 3.11+
- [Hermes Agent](https://hermes-agent.nousresearch.com) (optional — the CLI works standalone)
- No API keys. The tool uses public Solana RPCs and the free DexScreener API.

> **Always install from a trusted source.** Official packages are published to
> [PyPI](https://pypi.org/project/solana-rug/) and
> [GitHub Releases](https://github.com/rugpullnet/solana-rug/releases).
> The source is a single auditable Python file — no compiled binaries, no
> opaque dependencies. You can verify the checksums on the GitHub Releases page
> and compare against the source in this repo.

### Option A: Install as a Hermes Skill (recommended)

```bash
# From the Hermes Agent repo:
hermes skills install official/blockchain/solana-rug

# Or from a local checkout:
cd optional-skills/blockchain/solana-rug/
hermes skills install ./SKILL.md
```

Then ask in natural language:

```text
"Is token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 safe?"
"Rug-check F4J5LKyEQraMem8nspPAzwHXaaKMMDsxyt7GUK94pump"
"Scan wallet 9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM for risky tokens"
```

### Option B: Run the CLI Standalone

```bash
# Single file — no install needed (from GitHub Releases)
curl -OL https://github.com/rugpullnet/solana-rug/releases/latest/download/rugguard.py
python3 rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --md
```

```bash
# Or clone the repo
git clone https://github.com/rugpullnet/solana-rug.git
cd solana-rug
python3 scripts/rugguard.py --help
```

```bash
# Or pip install from PyPI (trusted source)
pip install solana-rug
solana-rug token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
```

### Verify It Works

```bash
python3 rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --json
```

Expected: BONK returns `safety_score: 100`, zero warnings, market data showing $682k liquidity on Meteora.

---

## How to Use

### Token Analysis

```bash
# JSON output (default) — pipe through jq
python3 rugguard.py token <MINT_ADDRESS>

# Human-readable Markdown report
python3 rugguard.py token <MINT_ADDRESS> --md

# Full example
python3 rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --md
```

JSON output includes a `market_data` block with DexScreener enrichment:

```json
{
  "safety_score": 100,
  "risk_level": "LOW",
  "flags": {
    "mint_authority_active": false,
    "freeze_authority_active": false,
    "sniper_detected": false,
    "suspicious_name": false,
    "sub_penny_price": false,
    "deployer_can_crash_price": false
  },
  "market_data": {
    "dex": "meteora",
    "liquidity_usd": 682156.92,
    "volume_24h": 936.68,
    "price_usd": 0.000004892,
    "price_change_24h": -2.92,
    "txns_24h": 212
  }
}
```

### Wallet Scan

```bash
python3 rugguard.py wallet <ADDRESS>
```

Scans all SPL tokens held by a wallet. For each token with meaningful balance, checks mint authority. Returns a prioritized list of risky tokens ordered by safety score (lowest first).

### Watch Mode, History, and Webhooks

```bash
# One check, store a SQLite history row, then exit
python3 rugguard.py watch <MINT_ADDRESS> --iterations 1

# Continuous monitoring every 60 seconds
python3 rugguard.py watch <MINT_ADDRESS> --interval 60

# Alert whenever score/flags/warnings change, or whenever safety <= 70
python3 rugguard.py watch <MINT_ADDRESS> --threshold 70 --webhook https://example.com/webhook
```

Watch mode stores every run in a local SQLite database and prints one JSON event per check:

```json
{
  "mint": "...",
  "safety_score": 79,
  "risk_level": "LOW",
  "changed": true,
  "reasons": ["score changed 82 -> 79"],
  "history_db": "~/.solana-rug/history.sqlite3"
}
```

Webhook payloads use the same JSON event shape and are sent only when a change/threshold alert fires.

### Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `SOLANA_RPC_URL` | `https://api.mainnet-beta.solana.com` | Override RPC endpoint. Set to a private node (Helius, QuickNode) for production reliability. |
| `SOLANA_RUG_HISTORY_DB` | `~/.solana-rug/history.sqlite3` | SQLite path for watch-mode score history. |
| `SOLANA_RUG_WEBHOOK_URL` | empty | Optional webhook URL for watch-mode alerts. |
| `SOLANA_RUG_WATCH_INTERVAL` | `60` | Default watch interval in seconds. |
| `SOLANA_RUG_HISTORY_RETENTION_DAYS` | `90` | Auto-prune history entries older than this many days. |
| `SOLANA_RUG_LIQ_THRESHOLD_CRITICAL` | `1000` | Liquidity below this USD amount is scored as critical risk (5pts). |
| `SOLANA_RUG_LIQ_THRESHOLD_HIGH` | `5000` | Liquidity below this is scored as high risk (4pts). |
| `SOLANA_RUG_LIQ_THRESHOLD_MEDIUM` | `20000` | Liquidity below this is scored as medium risk (3pts). |
| `SOLANA_RUG_LIQ_THRESHOLD_LOW` | `100000` | Liquidity below this is scored as low risk (1pt). |
| `SOLANA_RUG_LIQ_VOL_RATIO_WARNING` | `15` | Volume/liquidity ratio above this triggers a wash-trading warning (+3pts). |

---

## Architecture

### Data Flow

```
User Input (mint address)
        │
        ▼
┌─────────────────────┐
│  fetch_token_meta   │──► Solana RPC: getAccountInfo (jsonParsed)
│  (on-chain data)    │──► Token-2022 extension detection
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  check_authorities  │──► Mint authority, freeze authority, token program
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  fetch_token_holders│──► RPC: getTokenLargestAccounts
│                     │──► Falls back to DexScreener tx-count estimates
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  detect_liquidity   │──► RPC: getProgramAccounts (Raydium, pumpSwap, Orca)
│                     │──► Falls back to DexScreener for pool data
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  check_sniper_pat.  │──► First 15 mint signatures → rapid-buy detection
│  estimate_token_age │──► Signature pagination + DexScreener fallback
│  check_suspicious   │──► Name/symbol keyword blacklist
│  check_honeypot     │──► Jupiter quote API (optional check)
│  compute_dump_risk  │──► Deployer % vs pool liquidity
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  DexScreener enrich │──► Price, volume, liquidity, 24h change, tx count
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Scoring Engine     │──► 13 risk factors → 0-100 safety score
│  + Markdown/JSON    │──► Human-readable report or structured data
└─────────────────────┘
```

### Directory Layout

```
solana-rug/
├── SKILL.md                    # Hermes skill definition (docs all 13 checks)
├── scripts/
│   └── rugguard.py            # Core engine (~1470 lines, stdlib-only)
├── solana_rug/                 # PyPI package wrapper
│   ├── __init__.py
│   └── py.typed
├── pyproject.toml
├── tests/
│   └── test_checks.py         # 20 tests (13 unit + 7 blockchain integration)
├── README.md
├── CONTRIBUTING.md
└── LICENSE                     # MIT
```

### The 13 Risk Factors

Each factor contributes zero or more points to the total risk score. Higher total risk = lower safety score.

| # | Factor | Max | What It Catches | Data Source |
|---|--------|:---:|-----------------|-------------|
| 1 | Mint Authority | 15 | Dev can print unlimited new tokens | RPC |
| 2 | Freeze Authority | 5 | Dev can freeze accounts | RPC |
| 3 | LP Locked/Burned | 15 | LP tokens can be pulled, no pool exists | RPC + DexScreener |
| 4 | Liquidity Size | 5 | Pool under $20k → high price impact | DexScreener |
| 5 | Holder Concentration | 10 | Top 10 wallets own >50% of supply | RPC + DexScreener |
| 6 | Dev Risk | 5 | Dev holds >15% of supply | RPC |
| 7 | Token Age | 5 | Under 7 days old → statistically riskier | DexScreener |
| 8 | Mint History | 5 | Dev minted more tokens after launch | RPC |
| 9 | Honeypot | 10 | Sell simulation fails | Jupiter API |
| 10 | Sniper Bots | 10 | Bots bought within first 20 seconds | RPC sig analysis |
| 11 | Suspicious Name | 5 | Name contains "rug", "scam", "ponzi", etc. | On-chain + DexScreener |
| 12 | Sub-Penny Price | 5 | Price < $0.0001 on a young or thin token | DexScreener |
| 13 | Deployer Dump Risk | 5 | Dev could crash price by selling | DexScreener + RPC |

### How Risks Are Scored

Each check is independent and deterministic. The total risk sum has **no upper cap** — a token with every flag maxed out scores 0/100. The 13 factors are split across:

- **3 on-chain structural checks** (mint authority, freeze authority, LP locked/burned) — the classic rug vectors
- **4 market-health checks** (liquidity size, holder concentration, age, mint history) — sustainability signals
- **3 behavioral checks** (honeypot, snipers, name stigma) — adversarial pattern detection
- **3 position checks** (dev risk, sub-penny price, deployer dump risk) — who holds what and what that means

Score bands:

| Score | Risk | Meaning |
|:-----:|:----:|---------|
| 80-100 | LOW | On-chain mechanics clean. Standard DeFi risks only. |
| 50-79 | MEDIUM | Some risk factors present. Review flagged warnings. |
| 20-49 | HIGH | Multiple red flags. Likely a risky token. |
| 0-19 | CRITICAL | Strong evidence of malicious setup. |

### Data Sources (in order of preference)

1. **Solana public RPC** — Mint accounts, token holders, signatures, program accounts. Retries across 4 public endpoints with round-robin fallback.
2. **DexScreener API** — Real pool data when `getProgramAccounts` is rate-limited. Provides price, liquidity, volume, pair info, and creation time.
3. **Jupiter quote API** — Optional honeypot check. Simulates a buy/sell to detect trade restrictions.

All calls are cached in-memory with a 5-minute TTL to avoid redundant network requests.

---

## Support

Solana Rug Guard is free, open-source MIT software. No paywalls, no API keys, no registration.

If the tool saved you from a bad trade or helped you understand what happened to a coin you created, consider supporting the project by grabbing a small bag of **$RUG** on PumpSwap.

```
Token: F4J5LKyEQraMem8nspPAzwHXaaKMMDsxyt7GUK94pump
DEX:   pumpSwap (RUG/SOL pair)
```

Or check the current chart on DexScreener:

```
https://dexscreener.com/solana/4sHKYieWsGtrmtqjdXPRzSdVywXZ1jUQGbM8QbkBXMB9
```

Every buy adds liquidity to the pool and helps keep this project sustainable.

---

*MIT License · Built for Hermes Agent · No paid APIs required*
