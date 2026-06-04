FROM python:3.12-slim

WORKDIR /app

# Install solana-rug and its Telegram bot dependencies
COPY scripts/ scripts/
COPY solana_rug/ solana_rug/
COPY pyproject.toml setup.py ./

RUN pip install --no-cache-dir . python-telegram-bot

ENV TELEGRAM_BOT_TOKEN=""
ENV SOLANA_RPC_URL=""

CMD ["python", "-m", "scripts.telegram_bot"]
