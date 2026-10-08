#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v docker >/dev/null || { echo "Docker is required" >&2; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose plugin is required" >&2; exit 1; }
if [[ ! -f .env ]]; then
  echo "Missing .env. Run: cp .env.example .env, then review it." >&2
  exit 1
fi
mkdir -p data
chown 10001:10001 data
chmod 750 data
docker compose config --quiet
if [[ -f data/anulist.db ]] && docker compose ps --status running --services | grep -qx anulist; then
  echo "Creating pre-deployment backup..."
  docker compose exec -T anulist python /app/scripts/backup.py
elif [[ -f data/anulist.db ]]; then
  echo "Existing database found but container isn't running; take an offline backup before deployment."
  exit 1
fi
docker compose build
docker compose up -d --remove-orphans
docker compose ps
echo "AnuList deployed. By default the service binds to 127.0.0.1:8765 only."
