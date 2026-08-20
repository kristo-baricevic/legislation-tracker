#!/usr/bin/env bash
set -euo pipefail

E2E_DATABASE_PATH="/private/tmp/legislation-tracker-e2e.sqlite3"
rm -f "$E2E_DATABASE_PATH"

export DATABASE_URL="sqlite:////private/tmp/legislation-tracker-e2e.sqlite3"
export DJANGO_SETTINGS_MODULE="config.settings.dev"
export USE_LOCAL_DOCUMENT_STORAGE="True"
export CORS_ALLOWED_ORIGINS="http://127.0.0.1:3100"

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py shell -c '
from apps.legislation.models import Topic
Topic.objects.get_or_create(name="Education", defaults={"slug": "education"})
Topic.objects.get_or_create(name="Health", defaults={"slug": "health"})
'
exec .venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
