#!/bin/sh
# docker-entrypoint.sh — cron-like monitoring loop for solana-rug Docker image.
#
# Reads WATCH_TOKENS (comma-separated mint addresses) and checks each
# on the configured interval, storing results in SQLite and optionally
# posting webhook alerts.

set -e

if [ "$WATCH_TOKENS" = "***" ] || [ -z "$WATCH_TOKENS" ]; then
    echo "ERROR: WATCH_TOKENS env var is required (comma-separated mint addresses)"
    exit 1
fi

echo "=== Solana Rug Guard Docker Monitor ==="
echo "Watch list: $WATCH_TOKENS"
echo "Interval: ${WATCH_INTERVAL}s"
echo "History: $SQLITE_HISTORY"
echo "Webhook: ${WEBHOOK_URL:-disabled}"
echo ""

# Trap SIGTERM for graceful shutdown
trap 'echo "Shutting down..."; exit 0' SIGTERM SIGINT

while true; do
    echo "[$(date -u +'%Y-%m-%dT%H:%M:%SZ')] Checking tokens..."

    OLD_IFS="$IFS"
    IFS=','
    for mint in $WATCH_TOKENS; do
        mint=$(echo "$mint" | tr -d ' ')
        echo "  Checking $mint..."

        if [ -n "$WEBHOOK_URL" ]; then
            python3 -m scripts.rugguard token "$mint" --json 2>/dev/null | \
                curl -s -X POST "$WEBHOOK_URL" \
                    -H "Content-Type: application/json" \
                    -d @- >/dev/null 2>&1 && \
                echo "    Webhook sent" || \
                echo "    Webhook failed"
        fi

        # Also store in history via watch command (if history is persisted)
        env SQLITE_HISTORY="$SQLITE_HISTORY" \
            python3 -m scripts.rugguard watch "$mint" \
                --iterations 1 --interval 1 \
                --history "$SQLITE_HISTORY" \
                ${WEBHOOK_URL:+--webhook "$WEBHOOK_URL"} \
                ${THRESHOLD:+--threshold "$THRESHOLD"} \
                2>&1 | sed 's/^/    /'
    done
    IFS="$OLD_IFS"

    echo "  Sleeping for ${WATCH_INTERVAL}s..."
    sleep "$WATCH_INTERVAL" &
    wait $!
done
