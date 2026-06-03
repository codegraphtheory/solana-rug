# 🔍 $RUG Token Forensics Report

**Token:** `F4J5LKyEQraMem8nspPAzwHXaaKMMDsxyt7GUK94pump`  
**Symbol:** $RUG  
**Name:** Rugpull  
**Created:** June 2, 2026 · 04:24 UTC  
**Age at time of analysis:** ~1.9 days  
**Source code used:** `solana-rug` v0.1.0 (Hermes Agent skill)

---

## 1. Token Fundamentals

| Property | Value | Verified |
|----------|-------|----------|
| **Token Program** | Token-2022 (`TokenzQdBNb...`) | ✅ On-chain |
| **Decimals** | 6 | ✅ On-chain |
| **Total Supply** | 999,999,927,698,532 raw (≈999,999,928 tokens) | ✅ On-chain |
| **Extensions** | `metadataPointer`, `tokenMetadata` | ✅ On-chain |
| **Mint Authority** | ✅ Revoked (set to null) | ✅ On-chain |
| **Freeze Authority** | ✅ Revoked (set to null) | ✅ On-chain |

**Assessment:** The token is a standard Pump.fun Token-2022 deployment. Mint and freeze authorities are properly revoked — the dev cannot mint more tokens or freeze accounts. No transfer fee or transfer hook extensions are active. No hidden mechanics detected.

---

## 2. Market Data (DexScreener Verified)

| Metric | Value | Source |
|--------|-------|--------|
| **DEX** | pumpSwap (Pump.fun AMM) | DexScreener |
| **Trading Pair** | RUG / SOL | DexScreener |
| **Liquidity** | **$6,929 USD** | DexScreener |
| **24h Volume** | $16,584 | DexScreener |
| **Price** | **$0.00000956 per RUG** | DexScreener |
| **24h Price Change** | +8.79% 📈 | DexScreener |
| **24h Trades** | 200 buys / 202 sells (402 total) | DexScreener |
| **Age from Indexer** | ~1.9 days (June 2, 04:24 UTC) | DexScreener |

**Assessment:** The token bonded to pumpSwap (Pump.fun's native AMM). It has genuine liquidity of ~$7k and active daily trading volume of ~$16.5k. The price is up ~9% in the last 24 hours. Trading activity is roughly balanced (50/50 buy/sell ratio).

---

## 3. Safety Score Breakdown

**Overall: 94/100 — LOW RISK** *(but see notes below)*

| Risk Factor | Max Points | Score | Reason |
|-------------|:----------:|:-----:|--------|
| Mint Authority | 20 | 0 | ✅ Revoked — dev cannot mint |
| Freeze Authority | 10 | 0 | ✅ Revoked — no freeze risk |
| Liquidity (locked/burned) | 20 | 0 | ✅ pumpSwap pool with locked LP |
| Liquidity (size/thin) | 5 | 3 | ⚠️ $7k liquidity — moderate impact risk |
| Holder Concentration | 15 | 0 | ✅ ~100 active holders, no extreme concentration |
| Dev Risk | 10 | 0 | ✅ Dev holds 6.8% — below warning threshold |
| Token Age | 5 | 3 | ⚠️ Only 1.9 days old — early stage |
| Mint History | 5 | 0 | ✅ No post-launch mints detected |
| Honeypot | 10 | 0 | ✅ Token is actively traded on pumpSwap |

---

## 4. Deployer Wallet Analysis

| Detail | Value |
|--------|-------|
| **Deployer Address** | `8FQKqjDh...QCeN` |
| **Still Holds $RUG?** | ✅ Yes — **67,948,193 tokens (≈6.8% of supply)** |
| **Current Value** | ~$650 USD at current price |

**Assessment:** The deployer still holds a significant bag (~$650 worth). This is not unusual for a Pump.fun creator who hasn't fully exited. The 6.8% holding is below the 15% threshold that triggers a dev-risk flag.

---

## 5. Transaction Forensics — The Bot Sniper Attack

The following analysis is based on raw on-chain transaction data from the mint's first 50 transactions.

### Timeline

| Time (T+0 = creation) | Event | Wallet | Detail |
|-----------------------|-------|--------|--------|
| **T+0s** | Token created | `8FQKqjDh...QCeN` (deployer) | Pump.fun bonding curve deployed |
| **T+2s** | Sniper #1 | `V21GW8PG...m2n9` | Bought 1.84T raw tokens — dumped same tx |
| **T+4s** | Sniper #2 | `FYV59a3s...VoRw` | Bought **11.66T tokens** — ⚠️ STILL HOLDING |
| **T+5s** | Sniper #3 | `EmhADPsP...XPL1` | Bought 2.02T — dumped |
| **T+7s** | Sniper #4 | `4v7t3fmG...VhAa` | Bought 3.15T — ⚠️ STILL HOLDING |
| **T+9s** | Sniper #5 | `5kC79Y1F...D2q3` | Bought 6.17T — dumped 2 blocks later |
| **T+14m** | Activity quietens | — | 50 transactions in first 14 minutes |
| **+24h** | Normal trading | — | 400+ trades, $16.5k volume |

### Sniper Wallet Status

| Wallet | Bought (raw) | Status | Outcome |
|--------|:-----------:|--------|---------|
| `V21GW8PG...m2n9` | 1.84T | ✅ Dumped same tx | Lost SOL in fees |
| `FYV59a3s...VoRw` | 11.66T | ❌ **Still holding** | Underwater (bag holder) |
| `EmhADPsP...XPL1` | 2.02T | ✅ Dumped | Lost SOL in fees |
| `4v7t3fmG...VhAa` | 3.15T | ❌ **Still holding** | Underwater |
| `5kC79Y1F...D2q3` | 6.17T | ✅ Dumped in 2 blocks | Lost ~0.08 SOL |

### Key Finding: None of the snipers made a profit

Every sniper wallet that touched this token **lost money**. They all bought at the bonding curve's initial price and could not sell at a profit. The token had a brief pump followed by a dump, leaving the snipers holding bags or taking small losses.

A recurring fee address `EXKDUEjw...Lwtp` appears in almost every early transaction as a SOL recipient — this is Pump.fun's protocol fee collector (standard behavior, not a tax wallet).

---

## 6. What Happened (Summary)

1. **You deployed** $RUG on Pump.fun at June 2, 04:24 UTC
2. **Bot snipers** bought within 2 seconds using priority fees, expecting a quick flip
3. **The token pumped briefly**, then sold off as snipers tried to exit
4. **Snipers failed to profit** — all exited at a loss or are still holding bags
5. **The token bonded to pumpSwap** (graduated from bonding curve) with ~$7k locked liquidity
6. **Normal trading resumed** — 400+ trades in 24h, $16.5k volume, price trending up 9%

---

## 7. Overall Assessment

```
✅ Standard Pump.fun Token-2022 with proper authority revocation
✅ No hidden transfer fees or malicious extensions
✅ Active liquidity on pumpSwap ($6,929 locked)
✅ Healthy trading volume ($16.5k/24h)
✅ Deployer still invested (holds 6.8%)
✅ No honeypot mechanics detected
```

**This coin is not a rug.** The snipers tried to front-run you but ended up losing money. The token has genuine liquidity, active trading, and clean on-chain mechanics. The dev (you) still holds tokens worth ~$650.

---

*Generated by solana-rug v0.1.0 · On-chain data via public Solana RPC · Market data via DexScreener API*  
*MIT Licensed · No paid APIs required*
