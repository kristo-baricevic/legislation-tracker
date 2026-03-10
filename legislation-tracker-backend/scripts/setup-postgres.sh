#!/usr/bin/env bash
# Start Postgres (and Redis, MinIO) and ensure .env exists for local dev.
# Run from legislation-tracker-backend:  bash scripts/setup-postgres.sh

set -e
cd "$(dirname "$0")/.."

echo "Starting Postgres, Redis, MinIO (docker compose up -d)..."
docker compose up -d

echo "Waiting for Postgres to be ready..."
for i in {1..30}; do
  if docker compose exec -T postgres pg_isready -U legislation 2>/dev/null; then
    echo "Postgres is ready."
    break
  fi
  if [[ $i -eq 30 ]]; then
    echo "Postgres did not become ready in time."
    exit 1
  fi
  sleep 1
done

if [[ ! -f .env ]]; then
  echo "Creating .env from .env.example..."
  cp .env.example .env
  echo "Edit .env and set DJANGO_SECRET_KEY (and optionally CONGRESS_API_KEY, GOVINFO_API_KEY)."
else
  echo ".env already exists."
fi

echo ""
echo "Next steps:"
echo "  1. source .venv/bin/activate   (or create venv: python -m venv .venv)"
echo "  2. pip install -r requirements/dev.txt"
echo "  3. python manage.py migrate"
echo "  4. python manage.py runserver"
echo ""
echo "DATABASE_URL in .env should be: postgres://legislation:legislation@localhost:5432/legislation"
