Output demos/demo.gif
Set Shell "bash"
Set FontSize 18
Set Width 1280
Set Height 720
Set Theme "Catppuccin Mocha"
Set TypingSpeed 50ms

Type "# Solana Rug Guard · 13-factor on-chain score" Enter
Sleep 600ms
Type "python3 scripts/rugguard.py --help" Enter
Sleep 3s

Hide
Type "python3 scripts/rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --md | head -18" Enter
Sleep 16s
Show

Type "python3 scripts/rugguard.py token DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --json | python3 -m json.tool | head -12" Enter
Sleep 6s