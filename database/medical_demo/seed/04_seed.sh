#!/bin/sh
# Runs inside medical-db during first-time init (local socket / localhost).
set -eu

echo "[medical_demo] Starting deterministic seed..."

# Init scripts run against the temporary local server via Unix socket.
export MEDICAL_DB_HOST="${MEDICAL_DB_HOST:-/var/run/postgresql}"
export MEDICAL_DB_NAME="${POSTGRES_DB:-medical_demo}"
export MEDICAL_DB_USER="${POSTGRES_USER:-medical_user}"
export MEDICAL_DB_PASSWORD="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
export SEED_PATIENT_COUNT="${SEED_PATIENT_COUNT:-200}"
export SEED_RANDOM_SEED="${SEED_RANDOM_SEED:-42}"

python3 /opt/medical_demo/seed_medical_demo.py

echo "[medical_demo] Seed finished."
