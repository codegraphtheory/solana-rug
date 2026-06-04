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

from analysis import RugReport, rug_check_token, rug_check_wallet
from cli import main

__all__ = ["RugReport", "rug_check_token", "rug_check_wallet", "main"]

if __name__ == "__main__":
    main()
