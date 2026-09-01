#!/usr/bin/env bash
set -euo pipefail

E2E_API_HOST="127.0.0.1"
E2E_API_PORT="${E2E_API_PORT:-18000}"
E2E_CLIENT_ORIGIN="${E2E_CLIENT_ORIGIN:-http://127.0.0.1:13100}"
E2E_CELERY_BROKER_DIR="$(mktemp -d /private/tmp/legislation-tracker-e2e-broker.XXXXXX)"
E2E_DATABASE_URL="${E2E_DATABASE_URL:-sqlite:////private/tmp/legislation-tracker-e2e.sqlite3}"
if [[ "$E2E_DATABASE_URL" == sqlite:* ]]; then
  E2E_DATABASE_PATH="${E2E_DATABASE_URL#sqlite:///}"
  rm -f "$E2E_DATABASE_PATH"
fi
mkdir -p "$E2E_CELERY_BROKER_DIR/queue" "$E2E_CELERY_BROKER_DIR/processed" \
  "$E2E_CELERY_BROKER_DIR/control"

export DATABASE_URL="$E2E_DATABASE_URL"
export DJANGO_SETTINGS_MODULE="config.settings.e2e"
export DJANGO_SECRET_KEY="legislation-tracker-e2e-secret-key-with-safe-test-length"
export USE_LOCAL_DOCUMENT_STORAGE="True"
export CORS_ALLOWED_ORIGINS="$E2E_CLIENT_ORIGIN"
export CSRF_TRUSTED_ORIGINS="$E2E_CLIENT_ORIGIN"
export E2E_CELERY_BROKER_DIR
export LLM_CREDENTIAL_ENCRYPTION_KEYS="e2e:MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

.venv/bin/python manage.py migrate --noinput
if [[ "$E2E_DATABASE_URL" != sqlite:* ]]; then
  # The PostgreSQL service is intentionally persistent between local runs; the
  # browser fixture is not. Reset only this explicitly isolated E2E database.
  .venv/bin/python manage.py flush --noinput
fi
.venv/bin/python scripts/seed-e2e-legislative-intelligence.py

.venv/bin/celery -A config worker --loglevel=warning --pool=solo --concurrency=1 \
  --without-gossip --without-mingle --without-heartbeat &
E2E_WORKER_PID=$!

cleanup() {
  kill "$E2E_WORKER_PID" 2>/dev/null || true
  wait "$E2E_WORKER_PID" 2>/dev/null || true
  rm -rf "$E2E_CELERY_BROKER_DIR"
}
trap cleanup EXIT INT TERM

.venv/bin/python manage.py runserver "$E2E_API_HOST:$E2E_API_PORT" --noreload
