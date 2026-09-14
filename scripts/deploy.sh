#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml)
COMMAND="${1:-deploy}"

usage() {
  cat <<'EOF'
Usage: scripts/deploy.sh [deploy|status|logs|down]

  deploy  Validate config, build/start stack, wait for health (default)
  status  Show compose service status
  logs    Tail recent logs (follow)
  down    Stop stack without removing volumes

Requires .env.production (copy from .env.production.example).
Requires an existing external Traefik network (TRAEFIK_NETWORK); this script
does not create Docker networks.
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
  [[ -f "$ENV_FILE" ]] || die "missing $ENV_FILE (copy from .env.production.example)"
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

check_traefik_network() {
  local network
  network="$(load_env_value TRAEFIK_NETWORK)"
  network="${network:-traefik}"
  if ! docker network inspect "$network" >/dev/null 2>&1; then
    die "Traefik network '$network' does not exist. Create/attach it with your Traefik stack first (this script will not create it)."
  fi
}

print_failure_logs() {
  echo "---- compose ps ----" >&2
  "${COMPOSE[@]}" ps >&2 || true
  echo "---- recent logs ----" >&2
  "${COMPOSE[@]}" logs --no-color --tail=120 >&2 || true
}

wait_for_health() {
  local deadline=$((SECONDS + 300))
  local backend_ok=0
  local frontend_ok=0

  echo "Waiting for healthy services..."
  while (( SECONDS < deadline )); do
    backend_ok=0
    frontend_ok=0

    if "${COMPOSE[@]}" exec -T backend \
      python -c "import json,urllib.request; p=json.loads(urllib.request.urlopen('http://127.0.0.1:8000/health').read()); assert p.get('status')=='ok' and p.get('backend')=='ok' and p.get('catalog_db')=='ok', p" \
      >/dev/null 2>&1; then
      backend_ok=1
    fi

    # Frontend has no HTTP healthcheck in base compose; require running container.
    if "${COMPOSE[@]}" ps --status running --services 2>/dev/null | grep -qx frontend; then
      frontend_ok=1
    fi

    if [[ "$backend_ok" -eq 1 && "$frontend_ok" -eq 1 ]]; then
      echo "Backend health OK; frontend container is running."
      return 0
    fi
    sleep 5
  done

  print_failure_logs
  die "timed out waiting for backend/frontend readiness"
}

cmd_deploy() {
  require_docker
  require_env_file
  check_traefik_network

  local app_host
  app_host="$(load_env_value APP_HOST)"
  [[ -n "$app_host" ]] || die "APP_HOST must be set in $ENV_FILE"

  echo "Validating compose config..."
  "${COMPOSE[@]}" config >/dev/null

  echo "Starting stack (build, remove orphans)..."
  if ! "${COMPOSE[@]}" up -d --build --remove-orphans; then
    print_failure_logs
    die "docker compose up failed"
  fi

  if ! wait_for_health; then
    exit 1
  fi

  echo
  echo "Deploy succeeded."
  echo "Open: https://${app_host}"
  "${COMPOSE[@]}" ps
}

cmd_status() {
  require_docker
  require_env_file
  "${COMPOSE[@]}" ps
}

cmd_logs() {
  require_docker
  require_env_file
  "${COMPOSE[@]}" logs -f --tail=200
}

cmd_down() {
  require_docker
  require_env_file
  # Do not remove volumes (-v)
  "${COMPOSE[@]}" down
}

case "$COMMAND" in
  deploy|"")
    cmd_deploy
    ;;
  status)
    cmd_status
    ;;
  logs)
    cmd_logs
    ;;
  down)
    cmd_down
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    die "unknown command: $COMMAND"
    ;;
esac
