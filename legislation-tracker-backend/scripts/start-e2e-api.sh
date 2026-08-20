#!/usr/bin/env bash
set -euo pipefail

E2E_DATABASE_PATH="/private/tmp/legislation-tracker-e2e.sqlite3"
E2E_API_HOST="127.0.0.1"
E2E_API_PORT="${E2E_API_PORT:-18000}"
E2E_CLIENT_ORIGIN="${E2E_CLIENT_ORIGIN:-http://127.0.0.1:13100}"
rm -f "$E2E_DATABASE_PATH"

export DATABASE_URL="sqlite:////private/tmp/legislation-tracker-e2e.sqlite3"
export DJANGO_SETTINGS_MODULE="config.settings.dev"
export USE_LOCAL_DOCUMENT_STORAGE="True"
export CORS_ALLOWED_ORIGINS="$E2E_CLIENT_ORIGIN"

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py shell -c '
from apps.legislation.models import Topic
Topic.objects.get_or_create(name="Education", defaults={"slug": "education"})
Topic.objects.get_or_create(name="Health", defaults={"slug": "health"})
'
exec .venv/bin/python manage.py runserver "$E2E_API_HOST:$E2E_API_PORT" --noreload
