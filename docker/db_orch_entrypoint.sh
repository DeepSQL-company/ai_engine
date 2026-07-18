#!/bin/sh
set -e

PORT="${DB_ORCH_PORT:-8001}"
HEALTH_URL="http://127.0.0.1:${PORT}/health"
INIT_URL="http://127.0.0.1:${PORT}/init"

python -m services.db_orch.main &
APP_PID=$!

until curl -sf "$HEALTH_URL" >/dev/null; do
  sleep 1
done

if [ "${DB_AUTO_INIT}" = "true" ] || [ "${DB_AUTO_INIT}" = "1" ]; then
  if [ -n "${DB_HOST:-}" ]; then
    INIT_JSON=$(printf '{"host":"%s","port":%s,"database":"%s","user":"%s","password":"%s","schema":"%s"}' \
      "$DB_HOST" "${DB_PORT:-5432}" "${DB_NAME:-demo}" "${DB_USER:-user}" "${DB_PASSWORD:-user}" "${DB_SCHEMA:-bookings}")

    if [ -n "${API_KEY:-}" ]; then
      curl -sf -X POST "$INIT_URL" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: ${API_KEY}" \
        -d "$INIT_JSON"
    else
      curl -sf -X POST "$INIT_URL" \
        -H "Content-Type: application/json" \
        -d "$INIT_JSON"
    fi
    echo
  else
    echo "DB_AUTO_INIT включён, но DB_HOST не задан — init пропущен" >&2
  fi
fi

wait "$APP_PID"
