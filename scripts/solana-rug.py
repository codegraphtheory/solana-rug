#!/usr/bin/env python3
"""solana-rug.py — Solana Rug Guard: on-chain rug-pull detection engine.

CLI usage:
    python solana-rug.py token <MINT_ADDRESS>
    python solana-rug.py wallet <WALLET_ADDRESS>

Python API:
    from rugguard import rug_check_token, rug_check_wallet, RugReport

MIT License — free, open-source, no paid APIs required.
"""

from __future__ import annotations


def _main() -> None:
    try:
        from rugguard.cli import main
    except ModuleNotFoundError:
        # Not installed — locate the bundled `rugguard` package relative to this
        # launcher (skill dir, or the repo root one level up).
        import os
        import sys

        here = os.path.dirname(os.path.abspath(__file__))
        for candidate in (here, os.path.dirname(here)):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
        from rugguard.cli import main

    main()


if __name__ == "__main__":
    _main()
