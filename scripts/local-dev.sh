#!/usr/bin/env bash
# Mac full-stack sandbox backed by an APFS clone of a verified cloud snapshot.
set -euo pipefail
PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
STATE="$PROJECT/.local-dev"
SNAPSHOT=$(realpath "$PROJECT/logs/cloud-snapshots/latest")
export QM_LOCAL_PROJECT="$PROJECT"
export QM_LOCAL_STATE="$STATE/project"
COMPOSE=(docker compose --env-file "$PROJECT/.env.local" -f "$PROJECT/docker-compose.yml" -f "$PROJECT/deploy/compose.local-dev.yml" --project-directory "$PROJECT")
TUNNEL_LABEL=com.quantmind.cloud-tunnel
TUNNEL_PLIST="$HOME/Library/LaunchAgents/$TUNNEL_LABEL.plist"

require_mac() {
  [ "$(uname -s)" = Darwin ] || { echo 'local-dev is Mac-only.' >&2; exit 1; }
  [ -f "$PROJECT/.env.local" ] || { echo 'Missing .env.local.' >&2; exit 1; }
}

clone_snapshot() {
  [ -f "$SNAPSHOT/COMPLETE" ] || { echo 'Pull and verify a cloud snapshot first.' >&2; exit 1; }
  [ ! -e "$STATE" ] || { echo 'Local sandbox already exists (or a previous init is incomplete).' >&2; exit 1; }
  for volume in redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
    ! docker volume inspect "quantmind-dev_$volume" >/dev/null 2>&1 || {
      echo "Existing local-dev volume: quantmind-dev_$volume" >&2
      exit 1
    }
  done
  mkdir -p "$QM_LOCAL_STATE/logs"
  for item in data db models results user_pools_local; do
    [ ! -e "$SNAPSHOT/project/$item" ] || cp -cR "$SNAPSHOT/project/$item" "$QM_LOCAL_STATE/$item"
  done
  for item in data db models results user_pools_local; do mkdir -p "$QM_LOCAL_STATE/$item"; done
  printf '%s\n' "$(basename "$SNAPSHOT")" > "$STATE/SNAPSHOT_ID"
}

restore_volume() {
  local name=$1 archive=$2
  docker run --rm -v "quantmind-dev_${name}:/target" -v "$SNAPSHOT:/snapshot:ro" \
    postgres:15-alpine sh -c "tar -xzf /snapshot/$archive -C /target"
}

initialize() {
  clone_snapshot
  "${COMPOSE[@]}" create db redis qwenpaw >/dev/null
  restore_volume redis-data redis-data.tar.gz
  restore_volume qwenpaw-data qwenpaw-data.tar.gz
  restore_volume qwenpaw-secrets qwenpaw-secrets.tar.gz
  restore_volume qwenpaw-backups qwenpaw-backups.tar.gz
  restore_volume qwenpaw-shared qwenpaw-shared.tar.gz
  "${COMPOSE[@]}" up -d db
  for _ in {1..60}; do
    [ "$(docker inspect -f '{{.State.Health.Status}}' quantmind-dev-db 2>/dev/null || true)" = healthy ] && break
    sleep 2
  done
  [ "$(docker inspect -f '{{.State.Health.Status}}' quantmind-dev-db)" = healthy ]
  docker exec -i quantmind-dev-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner' < "$SNAPSHOT/postgres.dump"
  "${COMPOSE[@]}" stop db >/dev/null
  touch "$STATE/READY"
  echo "Initialized local sandbox from $(cat "$STATE/SNAPSHOT_ID")."
}

stop_tunnel() {
  launchctl print "gui/$(id -u)/$TUNNEL_LABEL" >/dev/null 2>&1 || return 0
  launchctl bootout "gui/$(id -u)/$TUNNEL_LABEL"
}

start_tunnel() {
  [ -f "$TUNNEL_PLIST" ] || return 0
  launchctl print "gui/$(id -u)/$TUNNEL_LABEL" >/dev/null 2>&1 || \
    launchctl bootstrap "gui/$(id -u)" "$TUNNEL_PLIST"
}

start_local() {
  [ -f "$STATE/READY" ] || { echo 'Run scripts/local-dev.sh init first.' >&2; exit 1; }
  stop_tunnel
  if lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo 'Port 8000 is occupied; restoring cloud tunnel.' >&2
    start_tunnel
    exit 1
  fi
  local services=(db redis quantmind)
  [ "${1:-core}" != full ] || services+=(celery-worker data-gateway huntly rsshub qwenpaw)
  "${COMPOSE[@]}" up -d "${services[@]}"
  for _ in {1..90}; do
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
    sleep 2
  done
  curl -fsS http://127.0.0.1:8000/health >/dev/null
  echo "Local sandbox ready: API http://127.0.0.1:8000, Vite http://127.0.0.1:3000, snapshot $(cat "$STATE/SNAPSHOT_ID")."
}

stop_local() {
  "${COMPOSE[@]}" down
  start_tunnel
  for _ in {1..20}; do
    curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1 && break
    sleep 1
  done
  curl -fsS http://127.0.0.1:8000/health >/dev/null
  curl -fsS http://127.0.0.1:18080/health >/dev/null
  echo 'Local sandbox stopped; port 8000 points to the cloud tunnel again.'
}

require_mac
case "${1:-help}" in
  init) initialize ;;
  start) start_local "${2:-core}" ;;
  stop) stop_local ;;
  status)
    echo "snapshot=$(cat "$STATE/SNAPSHOT_ID" 2>/dev/null || echo uninitialized)"
    "${COMPOSE[@]}" ps
    ;;
  *) echo 'Usage: scripts/local-dev.sh {init|start [core|full]|stop|status}'; exit 2 ;;
esac
