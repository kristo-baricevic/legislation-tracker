#!/usr/bin/env bash
# Create the legislation DB and user for local Postgres (no Docker).
# Run after installing Postgres (e.g. brew install postgresql@16; brew services start postgresql@16).
# Usage: bash scripts/setup-postgres-local.sh

set -e

USER="${POSTGRES_USER:-legislation}"
PASS="${POSTGRES_PASSWORD:-legislation}"
DB="${POSTGRES_DB:-legislation}"

if ! command -v psql &>/dev/null; then
  echo "psql not found. Install PostgreSQL and ensure psql is on your PATH."
  echo "  macOS: brew install postgresql@16 && brew services start postgresql@16"
  exit 1
fi

echo "Creating user '$USER' and database '$DB'..."
echo "(Ignore 'already exists' errors if you've run this before.)"
echo ""

# Create user; ignore error if already exists
psql postgres -c "CREATE USER $USER WITH PASSWORD '$PASS' CREATEDB;" 2>/dev/null || true

# Create database; ignore error if already exists
psql postgres -c "CREATE DATABASE $DB OWNER $USER;" 2>/dev/null || true

echo ""
echo "Done. Use in .env:"
echo "  DATABASE_URL=postgres://$USER:$PASS@localhost:5432/$DB"
echo ""
echo "Then: python manage.py migrate"
echo ""
