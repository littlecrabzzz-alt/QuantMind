#!/usr/bin/env bash
# Mac full-stack sandbox; never invoke the old authority stack.
set -euo pipefail
# Read once so code synchronization cannot change a running shell's file offset.
if [ "${QM_SCRIPT_TEXT:-}" != "$0" ]; then
  export QM_SCRIPT_TEXT="$0"
  exec bash -c "$(< "$0")" "$0" "$@"
fi
PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
STATE="$PROJECT/.local-dev"
export QM_LOCAL_PROJECT="$PROJECT"
export QM_LOCAL_STATE="$STATE/project"
COMPOSE=(docker compose --project-name quantmind-dev --env-file "$PROJECT/.env.local" -f "$PROJECT/docker-compose.yml" -f "$PROJECT/deploy/compose.local-dev.yml" --project-directory "$PROJECT")
TUNNEL_LABEL=com.quantmind.cloud-tunnel
TUNNEL_PLIST="$HOME/Library/LaunchAgents/$TUNNEL_LABEL.plist"
LOCK="$PROJECT/logs/local-dev.lock"
ROLLBACK=none
RESTORE_TUNNEL=false
SERVICES=()

fail() { echo "$*" >&2; exit 1; }

require_mac() {
  [ "$(uname -s)" = Darwin ] || fail 'local-dev is Mac-only.'
  [ -f "$PROJECT/.env.local" ] || fail 'Missing .env.local.'
  [ -z "${DOCKER_HOST:-}" ] || fail 'Unset DOCKER_HOST; use the local Docker Desktop context.'
  local endpoint
  endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
  case "$endpoint" in
    "unix://$HOME/.docker/"*|unix:///var/run/docker.sock) ;;
    *) fail "Refusing non-local Docker endpoint: $endpoint" ;;
  esac
  [ "$(docker info --format '{{.OperatingSystem}}')" = 'Docker Desktop' ] || fail 'Expected local Docker Desktop daemon.'
}

start_tunnel() {
  [ -f "$TUNNEL_PLIST" ] || { echo 'Cloud tunnel plist is missing.' >&2; return 1; }
  launchctl print "gui/$(id -u)/$TUNNEL_LABEL" >/dev/null 2>&1 || \
    launchctl bootstrap "gui/$(id -u)" "$TUNNEL_PLIST"
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  set +e
  if [ "$ROLLBACK" = start ]; then
    # No services were running before this attempt. Preserve all volumes.
    if "${COMPOSE[@]}" stop "${SERVICES[@]}"; then
      [ "$RESTORE_TUNNEL" = false ] || start_tunnel
    else
      echo 'Rollback could not stop local services; inspect ports before restoring the tunnel.' >&2
    fi
  elif [ "$ROLLBACK" = init ]; then
    "${COMPOSE[@]}" stop db
    echo 'Initialization incomplete; data retained for inspection. READY was not created.' >&2
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK"
  exit "$rc"
}

lock_operation() {
  mkdir -p "$PROJECT/logs"
  mkdir "$LOCK" 2>/dev/null || fail "Another local-dev operation owns $LOCK; inspect its pid before removing a stale lock."
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  echo "$$" > "$LOCK/pid"
}

initialize() {
  local snapshot volumes item
  snapshot=$(realpath "$PROJECT/logs/cloud-snapshots/latest")
  [ -f "$snapshot/COMPLETE" ] || fail 'Pull and verify a cloud snapshot first.'
  [ ! -e "$STATE" ] || fail 'Local sandbox already exists (or a previous init is incomplete).'
  volumes=$(docker volume ls --format '{{.Name}}')
  for item in postgres-data redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
    if echo "$volumes" | grep -Fxq "quantmind-dev_$item"; then
      fail "Existing local-dev volume: quantmind-dev_$item; refusing to restore over it."
    fi
  done
  for item in postgres.dump redis-data.tar.gz qwenpaw-data.tar.gz qwenpaw-secrets.tar.gz qwenpaw-backups.tar.gz qwenpaw-shared.tar.gz; do
    [ -f "$snapshot/$item" ] || fail "Missing snapshot archive: $item"
  done
  mkdir -p "$QM_LOCAL_STATE/logs"
  for item in data db models results user_pools_local; do
    [ ! -e "$snapshot/project/$item" ] || cp -cR "$snapshot/project/$item" "$QM_LOCAL_STATE/$item"
    mkdir -p "$QM_LOCAL_STATE/$item"
  done
  printf '%s\n' "$(basename "$snapshot")" > "$STATE/SNAPSHOT_ID"
  ROLLBACK=init
  "${COMPOSE[@]}" create db redis qwenpaw >/dev/null
  for item in redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
    docker run --rm -v "quantmind-dev_$item:/target" -v "$snapshot:/snapshot:ro" \
      postgres:15-alpine sh -c 'tar -xzf "/snapshot/$1.tar.gz" -C /target' sh "$item"
  done
  "${COMPOSE[@]}" up -d db
  for _ in {1..60}; do
    [ "$(docker inspect -f '{{.State.Health.Status}}' quantmind-dev-db 2>/dev/null || true)" = healthy ] && break
    sleep 2
  done
  [ "$(docker inspect -f '{{.State.Health.Status}}' quantmind-dev-db)" = healthy ]
  docker exec -i quantmind-dev-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error --single-transaction' < "$snapshot/postgres.dump"
  "${COMPOSE[@]}" stop db >/dev/null
  touch "$STATE/READY"
  ROLLBACK=none
  echo "Initialized local sandbox from $(cat "$STATE/SNAPSHOT_ID")."
}

healthy() { curl --noproxy '*' --connect-timeout 2 --max-time 3 -fsS "http://127.0.0.1:$1/health" >/dev/null 2>&1; }

start_local() {
  local mode=${1:-core} running service current_env
  case "$mode" in core|full|research) ;; *) fail 'Mode must be core, full or research.' ;; esac
  [ -f "$STATE/READY" ] && [ -s "$STATE/SNAPSHOT_ID" ] || fail 'Run scripts/local-dev.sh init first.'
  SERVICES=(db redis quantmind)
  [ "$mode" != full ] || SERVICES+=(celery-worker data-gateway huntly rsshub qwenpaw)
  if [ "$mode" = research ] || { [ "$mode" = full ] && [ -f "$QM_LOCAL_STATE/data/research/settings.json" ]; }; then
    [ -f "$QM_LOCAL_STATE/data/research/settings.json" ] || fail 'Prepare the research snapshot before starting research mode.'
    SERVICES+=(research-worker)
  fi
  running=$("${COMPOSE[@]}" ps --status running --services)
  if [ -n "$running" ]; then
    for service in "${SERVICES[@]}"; do
      echo "$running" | grep -Fxq "$service" || fail 'Sandbox is partially running or uses another mode; inspect status and stop before changing modes.'
    done
    current_env=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' quantmind-dev)
    echo "$current_env" | grep -Fxq 'QM_NODE_ROLE=sandbox' || fail 'Existing backend is not a sandbox.'
    echo "$current_env" | grep -Fxq "HOST_RUNTIME_PATH=$QM_LOCAL_STATE" || fail 'Existing sandbox predates runtime isolation; stop and start it to apply the fix.'
    healthy 8000 || fail 'Existing sandbox is unhealthy; inspect it before restarting.'
    echo 'Local sandbox is already running; no services or tunnels changed.'
    return
  fi
  if launchctl print "gui/$(id -u)/$TUNNEL_LABEL" >/dev/null 2>&1; then
    RESTORE_TUNNEL=true
    [ -f "$TUNNEL_PLIST" ] || fail 'Missing tunnel plist; cannot guarantee recovery.'
  fi
  # Install recovery before the first state change, including tunnel shutdown.
  ROLLBACK=start
  [ "$RESTORE_TUNNEL" = false ] || launchctl bootout "gui/$(id -u)/$TUNNEL_LABEL"
  for _ in {1..10}; do
    ! lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 && break
    sleep 1
  done
  ! lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || fail 'Port 8000 is occupied.'
  "${COMPOSE[@]}" up -d "${SERVICES[@]}"
  for _ in {1..90}; do healthy 8000 && break; sleep 2; done
  healthy 8000 || fail 'Local API health check failed; rolling back this start.'
  ROLLBACK=none
  echo "Local sandbox ready: API http://127.0.0.1:8000, snapshot $(cat "$STATE/SNAPSHOT_ID")."
}

stop_local() {
  local children name
  if [ -f "$QM_LOCAL_STATE/data/research/settings.json" ]; then
    local research_node research_children
    research_node=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["node_id"])' "$QM_LOCAL_STATE/data/research/settings.json")
    research_children=$(docker ps --filter "label=quantmind.research.node=$research_node" --format '{{.Names}}')
    [ -z "$research_children" ] || fail "Active isolated research computation: $research_children; cancel or finish it before switching backends."
  fi
  children=$(docker ps --filter network=quantmind-dev_quantmind-net --format '{{.Names}}')
  while IFS= read -r name; do
    case "$name" in
      qm-train-*|qm-agent-*|qm-frozen-*|qm-ide-run-*|rdagent-*)
        fail "Active sandbox child job: $name; finish or stop that job before switching backends." ;;
    esac
  done <<< "$children"
  "${COMPOSE[@]}" down
  echo 'Local sandbox stopped; all data volumes retained.'
  start_tunnel || fail 'Local stop succeeded; cloud tunnel could not be loaded.'
  for _ in {1..10}; do healthy 8000 && healthy 18080 && break; sleep 1; done
  healthy 8000 && healthy 18080 || fail 'Local stop succeeded; tunnel loaded but cloud is unreachable (possibly offline).'
  echo 'Ports 8000/18080 point to the cloud tunnel again.'
}

require_mac
case "${1:-help}" in
  init) lock_operation; initialize ;;
  start) lock_operation; start_local "${2:-core}" ;;
  restart-research-worker|restart-backend)
    lock_operation
    service=research-worker; container=quantmind-dev-research-worker
    if [ "$1" = restart-backend ]; then service=quantmind; container=quantmind-dev; fi
    [ "$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" | grep '^QM_NODE_ROLE=')" = QM_NODE_ROLE=sandbox ] || fail 'Expected an isolated sandbox service.'
    "${COMPOSE[@]}" restart "$service"
    ;;
  stop) lock_operation; stop_local ;;
  status)
    echo "snapshot=$(cat "$STATE/SNAPSHOT_ID" 2>/dev/null || echo uninitialized)"
    "${COMPOSE[@]}" ps
    ;;
  *) echo 'Usage: scripts/local-dev.sh {init|start [core|full|research]|restart-research-worker|restart-backend|stop|status}'; exit 2 ;;
esac
