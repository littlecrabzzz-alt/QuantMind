#!/usr/bin/env bash
# One-time consistent migration. Preseed first. Never overwrite a cloud authority.
set -euo pipefail
if [ "${QM_SCRIPT_TEXT:-}" != "$0" ]; then
  export QM_SCRIPT_TEXT="$0"
  exec bash -c "$(< "$0")" "$0" "$@"
fi
PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
source "$PROJECT/deploy/dual-node.env"
cd "$PROJECT"
umask 077
RSYNC=/opt/homebrew/bin/rsync
test -x "$RSYNC"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$PROJECT/logs/dual-node-$stamp"
remote_backup="$QM_REMOTE_ROOT/backups/migration-$stamp"
mkdir -p "$backup"
local_compose=(docker compose --env-file .env.local -f docker-compose.yml -f docker-compose.local.yml)
remote() { ssh -o BatchMode=yes -o ServerAliveInterval=30 "$QM_SSH_TARGET" "$@"; }

remote "sudo -n bash -c 'set -eu; test \"\$(findmnt -n -o UUID -T $QM_REMOTE_ROOT)\" = $QM_DISK_UUID; test ! -e $QM_REMOTE_ROOT/AUTHORITY'"
mkdir "$PROJECT/logs/dual-node-cutover.lock" || { echo 'Another cutover is active'; exit 1; }
frozen=false
completed=false
finish() {
  status=$?
  rmdir "$PROJECT/logs/dual-node-cutover.lock"
  if [ "$frozen" = true ] && [ "$completed" = false ]; then
    echo "Migration stopped ($status); backups: $backup. Writers remain stopped."
    echo 'Do not restart local writers until cloud AUTHORITY state has been checked.'
  fi
}
trap finish EXIT

# Do not interrupt independent model/backtest containers or in-flight Celery work.
if docker ps --format '{{.Names}}' | rg '^qm-(train|frozen|agent)-'; then
  echo 'A research job is active; retry after it finishes.' >&2
  exit 75
fi
docker exec quantmind-celery celery -A backend.services.engine.qlib_app.celery_config:celery_app \
  inspect active --json --timeout=15 > "$backup/celery-active.json"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(1 if not d else (75 if any(d.values()) else 0))' "$backup/celery-active.json"
docker inspect quantmind quantmind-celery quantmind-celery-beat quantmind-huntly qwenpaw \
  --format '{{.Name}} {{.State.Running}} {{.HostConfig.RestartPolicy.Name}}' > "$backup/local-services.txt"
echo 'Freezing QuantMind writers; unrelated services are untouched.'
frozen=true
"${local_compose[@]}" stop -t 120 celery-beat quantmind celery-worker huntly qwenpaw
"${local_compose[@]}" stop -t 60 redis
# Prevent Docker Desktop restarting a stale primary after a Mac reboot.
docker update --restart=no quantmind quantmind-celery quantmind-celery-beat quantmind-huntly qwenpaw quantmind-redis >/dev/null

docker exec quantmind-db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner' > "$backup/postgres.dump"
docker exec -i quantmind-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' \
  < deploy/table-counts.sql > "$backup/postgres-counts.txt"
for volume in redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
  # Full cold volume restore preserves the QwenPaw registry together with its files.
  # Later skill updates must still use quantbot_init.sh, never manual skill copying.
  docker run --rm --network none --entrypoint tar \
    -v "quantmind_$volume:/source:ro" quantmind-oss:latest \
    -C /source -czf - . > "$backup/$volume.tar.gz"
done
remote "sudo -n mkdir -p $remote_backup"
"$RSYNC" -a --partial --rsync-path='sudo -n rsync' "$backup/" "$QM_SSH_TARGET:$remote_backup/"

paths=(data db models)
for path in results* user_pools_local; do
  [ ! -d "$path" ] || paths+=("$path")
done
for path in "${paths[@]}"; do
  # Deletions are scoped to one runtime subtree and retained in displaced/.
  excludes=(--exclude=.DS_Store --exclude=.rsync-partial --exclude=__pycache__)
  if [ "$path" = data ]; then excludes+=(--exclude='/upgrade_v*.sql' --exclude='/stocks/'); fi
  if [ "$path" = db ]; then excludes+=(--exclude='/sql/'); fi
  "$RSYNC" -a --no-owner --no-group --checksum --compress --partial \
    --delete-delay --backup --backup-dir="$remote_backup/displaced/$path" \
    "${excludes[@]}" --rsync-path='sudo -n rsync' \
    "$path/" "$QM_SSH_TARGET:$QM_REMOTE_PROJECT/$path/"
done
python3 scripts/dual_node_inventory.py "$PROJECT" > "$backup/runtime-manifest.jsonl"
remote "sudo -n python3 $QM_REMOTE_PROJECT/scripts/dual_node_inventory.py $QM_REMOTE_PROJECT" > "$backup/cloud-runtime-manifest.jsonl"
cmp "$backup/runtime-manifest.jsonl" "$backup/cloud-runtime-manifest.jsonl"
"$RSYNC" -a --rsync-path='sudo -n rsync' "$backup/" "$QM_SSH_TARGET:$remote_backup/"
# Verify the database dump and every cold archive end-to-end before restore.
(cd "$backup" && shasum -a 256 postgres.dump *.tar.gz runtime-manifest.jsonl > SHA256SUMS)
"$RSYNC" -a --rsync-path='sudo -n rsync' "$backup/SHA256SUMS" "$QM_SSH_TARGET:$remote_backup/"
remote "sudo -n bash -c 'cd $remote_backup && sha256sum -c SHA256SUMS'"
remote "sudo -n systemd-run --unit=quantmind-cutover --wait --collect --property=RequiresMountsFor=/root/data/disk /bin/bash $QM_REMOTE_PROJECT/scripts/dual-node-restore.sh $remote_backup"
completed=true
echo "Cutover complete. Local data retained as offline baseline. Backup: $remote_backup"
