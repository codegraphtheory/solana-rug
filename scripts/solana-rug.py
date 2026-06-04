#!/usr/bin/env python3
"""solana-rug — Standalone CLI launcher.

Usage:
    python solana-rug.py token <MINT_ADDRESS>
    python solana-rug.py wallet <WALLET_ADDRESS>
    python solana-rug.py compare <MINT1> <MINT2>
    python solana-rug.py badge <MINT_ADDRESS>
    python solana-rug.py timeline <MINT_ADDRESS>
    python solana-rug.py watch <MINT_ADDRESS> [options]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rugguard.cli import main

main()
