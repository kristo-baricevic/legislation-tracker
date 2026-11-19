#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DOCKER_ENV_FILE="${DOCKER_ENV_FILE:-.env.docker}"
if [[ ! -f "$DOCKER_ENV_FILE" ]]; then
  printf '%s\n' "Missing $DOCKER_ENV_FILE. Copy .env.docker.example and fill in the required keys." >&2
  exit 1
fi
# Validate before building or changing any running service; never print secrets.
rtk proxy docker compose --env-file "$DOCKER_ENV_FILE" config --quiet
rtk proxy docker compose --env-file "$DOCKER_ENV_FILE" up -d --build --wait --wait-timeout 180
rtk proxy docker compose --env-file "$DOCKER_ENV_FILE" ps
