#!/usr/bin/env bash
# Solana Rug Guard CLI demo (not a Hermes profile).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
source demos/vhs/sanitize-recording-env.sh
echo "Solana Rug Guard - on-chain token scan"
python3 scripts/rugguard.py --help
python3 scripts/rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --md | head -20
python3 scripts/rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --json | python3 -m json.tool | head -14