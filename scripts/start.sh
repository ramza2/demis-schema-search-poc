#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

echo "Starting DEMIS Schema Search PoC (Step 1)..."
docker compose up --build -d
echo
echo "Services:"
docker compose ps
echo
echo "Backend health: http://localhost:${BACKEND_EXTERNAL_PORT:-8000}/health"
echo "Frontend:       http://localhost:${FRONTEND_EXTERNAL_PORT:-8501}"
