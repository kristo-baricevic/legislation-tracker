#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$repo_root/legislation-tracker-backend"
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/black --check .
.venv/bin/ruff check .
.venv/bin/pytest -q
.venv/bin/pip-audit -r requirements/production.lock

cd "$repo_root/legislation-tracker-client"
pnpm test
pnpm typecheck
pnpm lint
pnpm audit --prod
pnpm build --webpack

cd "$repo_root/legislation-tracker-extension"
node --test tests/*.test.js
node --check content.js
node --check extension-utils.js
node --check popup.js
