FROM python:3.12-slim

LABEL org.opencontainers.image.source="https://github.com/rugpullnet/solana-rug"
LABEL org.opencontainers.image.description="Solana Rug Guard — background monitoring container"

WORKDIR /app

# Install solana-rug from source
COPY scripts/ scripts/
COPY solana_rug/ solana_rug/
COPY pyproject.toml setup.py README.md ./
RUN pip install --no-cache-dir .

# Copy entrypoint
COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Persistent data volume
VOLUME /data

# Default config via env
ENV WATCH_TOKENS=""
ENV WATCH_INTERVAL=300
ENV WEBHOOK_URL=""
ENV SQLITE_HISTORY=/data/history.sqlite3
ENV SOLANA_RPC_URL=""

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python3 -c "import os; exit(0 if os.path.isfile(os.environ.get('SQLITE_HISTORY','/data/history.sqlite3')) else 1)"

ENTRYPOINT ["/entrypoint.sh"]
