#!/usr/bin/env bash
# Safely drain the cloud Tushare worker without revoking or killing active work.
set -euo pipefail

# Read once so a Syncthing update cannot change a running operation.
if [ "${QM_TUSHARE_DRAIN_SCRIPT_TEXT:-}" != "$0" ]; then
  export QM_TUSHARE_DRAIN_SCRIPT_TEXT="$0"
  exec bash -c "$(< "$0")" "$0" "$@"
fi

PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
source "$PROJECT/deploy/dual-node.env"
APP=backend.services.engine.qlib_app.celery_config:celery_app
QUEUE=tushare_acquire
WORKER_SERVICE=tushare-worker
WORKER_CONTAINER=quantmind-tushare-worker
timeout=600
poll_seconds=${QM_TUSHARE_DRAIN_POLL_SECONDS:-2}

usage() {
  echo 'Usage: sudo -n bash scripts/tushare-worker-drain.sh [--timeout SECONDS]' >&2
  exit 2
}

if [ "${1:-}" = --timeout ]; then
  [ "$#" = 2 ] || usage
  timeout=$2
elif [ "$#" != 0 ]; then
  usage
fi
[[ "$timeout" =~ ^[0-9]+$ ]] && [ "$timeout" -ge 1 ] && [ "$timeout" -le 3600 ] || usage
[[ "$poll_seconds" =~ ^[0-9]+$ ]] && [ "$poll_seconds" -ge 1 ] || usage

[ "$(id -u)" = 0 ] || { echo 'Run as root on the cloud authority.' >&2; exit 1; }
[ "$(hostname)" = "$QM_CLOUD_HOSTNAME" ] || { echo 'Cloud hostname mismatch.' >&2; exit 1; }
[ "$PROJECT" = "$QM_REMOTE_PROJECT" ] || { echo 'Cloud project path mismatch.' >&2; exit 1; }
[ "$(findmnt -n -o UUID -T "$QM_REMOTE_ROOT")" = "$QM_DISK_UUID" ] || {
  echo 'Cloud authority disk mismatch.' >&2
  exit 1
}

compose() {
  bash "$PROJECT/scripts/dual-node.sh" cloud-compose "$@"
}

inspect_value() {
  local kind=$1 payload
  payload=$(docker exec "$worker_id" celery -A "$APP" inspect "$kind" \
    --json --timeout=15 --destination "$worker_node") || return 1
  python3 -c '
import json, sys
node, kind = sys.argv[1:]
value = json.load(sys.stdin)
if set(value) != {node} or not isinstance(value[node], list):
    raise SystemExit(2)
if kind == "active_queues":
    print(sum(item.get("name") == "tushare_acquire" for item in value[node]
              if isinstance(item, dict)))
else:
    print(len(value[node]))
' "$worker_node" "$kind" <<<"$payload"
}

# Beat must stop before the only acquisition consumer is cancelled.
compose stop celery-beat
worker_id=$(compose ps -q "$WORKER_SERVICE")
[[ "$worker_id" =~ ^[a-f0-9]{12,64}$ ]] || {
  echo 'Expected exactly one Tushare worker container; Beat remains stopped.' >&2
  exit 75
}
[ "$(docker inspect --format '{{.Name}}' "$worker_id")" = "/$WORKER_CONTAINER" ] || {
  echo 'Tushare worker container mismatch; Beat remains stopped.' >&2
  exit 75
}
worker_host=$(docker exec "$worker_id" hostname)
[[ "$worker_host" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]] || {
  echo 'Invalid Tushare worker hostname; Beat remains stopped.' >&2
  exit 75
}
worker_node="celery@$worker_host"

docker exec "$worker_id" celery -A "$APP" control cancel_consumer "$QUEUE" \
  --timeout=15 --destination "$worker_node" >/dev/null

deadline=$((SECONDS + timeout))
idle_rounds=0
while [ "$SECONDS" -lt "$deadline" ]; do
  queue_count=$(inspect_value active_queues) || {
    echo 'Celery queue inspection failed; worker remains running and Beat remains stopped.' >&2
    exit 75
  }
  active_count=$(inspect_value active) || {
    echo 'Celery active inspection failed; worker remains running and Beat remains stopped.' >&2
    exit 75
  }
  reserved_count=$(inspect_value reserved) || {
    echo 'Celery reserved inspection failed; worker remains running and Beat remains stopped.' >&2
    exit 75
  }
  if [ "$queue_count" = 0 ] && [ "$active_count" = 0 ] && [ "$reserved_count" = 0 ]; then
    idle_rounds=$((idle_rounds + 1))
    if [ "$idle_rounds" -ge 2 ]; then
      compose stop -t 300 "$WORKER_SERVICE"
      [ -z "$(compose ps --status running -q "$WORKER_SERVICE")" ] || {
        echo 'Tushare worker still reports running after a clean drain.' >&2
        exit 1
      }
      echo "Drained and stopped $worker_node after two stable idle inspections."
      exit 0
    fi
  else
    idle_rounds=0
  fi
  sleep "$poll_seconds"
done

echo 'Drain timed out; worker remains running, Beat remains stopped, and no task was revoked.' >&2
exit 75
