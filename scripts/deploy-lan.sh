#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env.lan}"
COMMAND="${1:-deploy}"

usage() {
  cat <<'EOF'
Usage: scripts/deploy-lan.sh [deploy|status|logs|down]

  deploy  Validate, build/start GPU-server LAN stack, wait for health (default)
  status  Show stack status
  logs    Follow recent logs
  down    Stop stack without deleting volumes

Environment:
  ENV_FILE=.env.lan
  LAN_BIND_IP=<GPU server internal IPv4>
  ORACLE_TEST_ENABLED=true|false

This deployment does not use Traefik or public DNS.
Only the frontend is published to the configured LAN IP.
EOF
}

die() {
  echo "ERROR: $*" >&2
  exit 1
}

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker is not installed or not on PATH"
  docker compose version >/dev/null 2>&1 || die "docker compose plugin is required"
}

require_env_file() {
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (copy from .env.lan.example)"
}

load_env_value() {
  local key="$1"
  local line
  line="$(grep -E "^[[:space:]]*${key}=" "$ENV_FILE" | tail -n1 || true)"
  if [[ -z "$line" ]]; then
    echo ""
    return 0
  fi
  echo "${line#*=}" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

build_compose() {
  COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.lan.yml)
  local oracle_enabled
  oracle_enabled="$(load_env_value ORACLE_TEST_ENABLED)"
  if [[ "${oracle_enabled,,}" == "true" || "$oracle_enabled" == "1" || "${oracle_enabled,,}" == "yes" ]]; then
    COMPOSE+=(--profile oracle-test)
  fi
}

validate_lan_ip() {
  local lan_ip="$1"
  [[ -n "$lan_ip" ]] || die "LAN_BIND_IP must be set in $ENV_FILE"
  [[ "$lan_ip" != "127.0.0.1" && "$lan_ip" != "0.0.0.0" ]] || die "LAN_BIND_IP must be the GPU server's internal IPv4, not $lan_ip"

  if ! ip -4 addr show 2>/dev/null | grep -Fq "inet ${lan_ip}/"; then
    echo "Available IPv4 addresses on this server:" >&2
    ip -4 -br addr show >&2 || true
    die "LAN_BIND_IP '$lan_ip' is not assigned to this GPU server"
  fi
}

print_failure_logs() {
  echo "---- compose ps ----" >&2
  "${COMPOSE[@]}" ps >&2 || true
  echo "---- recent logs ----" >&2
  "${COMPOSE[@]}" logs --no-color --tail=150 >&2 || true
}

oracle_fixture_ready() {
  "${COMPOSE[@]}" exec -T oracle-test bash -lc '
    sqlplus -s "/ as sysdba" <<'"'"'SQL'"'"'
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET HEADING OFF FEEDBACK OFF PAGESIZE 0 VERIFY OFF ECHO OFF
ALTER SESSION SET CONTAINER=FREEPDB1;
DECLARE
  v_users  PLS_INTEGER;
  v_tables PLS_INTEGER;
  v_grants PLS_INTEGER;
BEGIN
  SELECT COUNT(*) INTO v_users
    FROM DBA_USERS
   WHERE USERNAME IN ('"'"'DEMIS_OWNER'"'"', '"'"'DEMIS_RO'"'"');

  SELECT COUNT(*) INTO v_tables
    FROM DBA_TABLES
   WHERE OWNER = '"'"'DEMIS_OWNER'"'"';

  SELECT COUNT(*) INTO v_grants
    FROM DBA_TAB_PRIVS
   WHERE OWNER = '"'"'DEMIS_OWNER'"'"'
     AND GRANTEE = '"'"'DEMIS_RO'"'"'
     AND PRIVILEGE = '"'"'SELECT'"'"';

  IF v_users != 2 OR v_tables != 25 OR v_grants != 25 THEN
    RAISE_APPLICATION_ERROR(
      -20001,
      '"'"'DEMIS fixture incomplete users='"'"' || v_users ||
      '"'"' tables='"'"' || v_tables ||
      '"'"' grants='"'"' || v_grants
    );
  END IF;
END;
/
EXIT;
SQL
  ' >/dev/null 2>&1
}

ensure_oracle_fixture() {
  local oracle_enabled
  oracle_enabled="$(load_env_value ORACLE_TEST_ENABLED)"
  if [[ ! ("${oracle_enabled,,}" == "true" || "$oracle_enabled" == "1" || "${oracle_enabled,,}" == "yes") ]]; then
    return 0
  fi

  if oracle_fixture_ready; then
    echo "Oracle DEMIS mock fixture already initialized."
    return 0
  fi

  echo "Initializing Oracle DEMIS mock fixture..."
  "${COMPOSE[@]}" exec -T oracle-test bash /opt/demis-bootstrap/01_users.sh
  "${COMPOSE[@]}" exec -T oracle-test bash -lc 'sqlplus -s "/ as sysdba" @/opt/demis-bootstrap/02_schema.sql'

  if ! oracle_fixture_ready; then
    print_failure_logs
    die "Oracle DEMIS mock fixture verification failed"
  fi

  echo "Oracle DEMIS mock fixture verified: users=2 tables=25 select_grants=25."
}

wait_for_stack() {
  local oracle_enabled
  oracle_enabled="$(load_env_value ORACLE_TEST_ENABLED)"
  local deadline=$((SECONDS + 900))

  echo "Waiting for backend/frontend and enabled fixtures..."
  while (( SECONDS < deadline )); do
    local backend_ok=0
    local frontend_ok=0
    local oracle_ok=1

    if "${COMPOSE[@]}" exec -T backend \
      python -c "import json,urllib.request; p=json.loads(urllib.request.urlopen('http://127.0.0.1:8000/health').read()); assert p.get('status')=='ok' and p.get('backend')=='ok' and p.get('catalog_db')=='ok', p" \
      >/dev/null 2>&1; then
      backend_ok=1
    fi

    if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx frontend; then
      frontend_ok=1
    fi

    if [[ "${oracle_enabled,,}" == "true" || "$oracle_enabled" == "1" || "${oracle_enabled,,}" == "yes" ]]; then
      oracle_ok=0
      local oracle_id
      oracle_id="$("${COMPOSE[@]}" ps -q oracle-test 2>/dev/null || true)"
      if [[ -n "$oracle_id" ]]; then
        local health
        health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$oracle_id" 2>/dev/null || true)"
        [[ "$health" == "healthy" ]] && oracle_ok=1
      fi
    fi

    if [[ "$backend_ok" -eq 1 && "$frontend_ok" -eq 1 && "$oracle_ok" -eq 1 ]]; then
      echo "LAN stack is ready."
      return 0
    fi
    sleep 5
  done

  print_failure_logs
  die "timed out waiting for LAN stack readiness"
}

cmd_deploy() {
  require_docker
  require_env_file
  build_compose

  local lan_ip
  lan_ip="$(load_env_value LAN_BIND_IP)"
  validate_lan_ip "$lan_ip"

  echo "Validating compose config..."
  "${COMPOSE[@]}" config >/dev/null

  echo "Starting GPU-server LAN stack..."
  if ! "${COMPOSE[@]}" up -d --build --remove-orphans; then
    print_failure_logs
    die "docker compose up failed"
  fi

  wait_for_stack
  ensure_oracle_fixture

  local frontend_port backend_port
  frontend_port="$(load_env_value FRONTEND_EXTERNAL_PORT)"
  backend_port="$(load_env_value BACKEND_EXTERNAL_PORT)"
  frontend_port="${frontend_port:-8501}"
  backend_port="${backend_port:-8000}"

  echo
  echo "Deploy succeeded."
  echo "Schema Analyzer: http://${lan_ip}:${frontend_port}"
  echo "Backend diagnostic (server only): http://127.0.0.1:${backend_port}"

  local oracle_enabled
  oracle_enabled="$(load_env_value ORACLE_TEST_ENABLED)"
  if [[ "${oracle_enabled,,}" == "true" || "$oracle_enabled" == "1" || "${oracle_enabled,,}" == "yes" ]]; then
    echo "Oracle target from backend: host=oracle-test port=1521 service=FREEPDB1 schema=DEMIS_OWNER user=DEMIS_RO"
  fi

  "${COMPOSE[@]}" ps
}

cmd_status() {
  require_docker
  require_env_file
  build_compose
  "${COMPOSE[@]}" ps
}

cmd_logs() {
  require_docker
  require_env_file
  build_compose
  "${COMPOSE[@]}" logs -f --tail=200
}

cmd_down() {
  require_docker
  require_env_file
  build_compose
  "${COMPOSE[@]}" down
}

case "$COMMAND" in
  deploy|"") cmd_deploy ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  down) cmd_down ;;
  -h|--help|help) usage ;;
  *) usage; die "unknown command: $COMMAND" ;;
esac
