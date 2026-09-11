#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Defaults for host-side pytest against compose-published ports
export MEDICAL_DB_HOST="${MEDICAL_DB_HOST:-localhost}"
export MEDICAL_DB_PORT="${MEDICAL_DB_PORT:-5433}"
export MEDICAL_DB_NAME="${MEDICAL_DB_NAME:-medical_demo}"
export MEDICAL_DB_USER="${MEDICAL_DB_USER:-medical_user}"
export MEDICAL_DB_PASSWORD="${MEDICAL_DB_PASSWORD:-medical_pass_change_me}"

export CATALOG_DB_HOST="${CATALOG_DB_HOST:-localhost}"
export CATALOG_DB_PORT="${CATALOG_DB_PORT:-5434}"
export CATALOG_DB_NAME="${CATALOG_DB_NAME:-schema_catalog}"
export CATALOG_DB_USER="${CATALOG_DB_USER:-catalog_user}"
export CATALOG_DB_PASSWORD="${CATALOG_DB_PASSWORD:-catalog_pass_change_me}"

cd backend
python -m pytest -q "$@"
