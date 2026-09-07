#!/usr/bin/env bash
# Invoked on the cloud only, after matching cold-file manifests and archive hashes.
set -euo pipefail
if [ "${QM_SCRIPT_TEXT:-}" != "$0" ]; then
  export QM_SCRIPT_TEXT="$0"
  exec bash -c "$(< "$0")" "$0" "$@"
fi
PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
source "$PROJECT/deploy/dual-node.env"
cd "$PROJECT"
umask 077
test "$(id -u)" = 0
test "$(findmnt -n -o UUID -T "$QM_REMOTE_ROOT")" = "$QM_DISK_UUID"
test ! -e "$QM_REMOTE_ROOT/AUTHORITY"
backup=$(realpath "${1:?migration backup required}")
case "$backup" in "$QM_REMOTE_ROOT"/backups/migration-*) ;; *) exit 2 ;; esac
(cd "$backup" && sha256sum -c SHA256SUMS)
compose=(bash scripts/dual-node.sh cloud-compose)
for volume in postgres-data redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
  mkdir -p "$QM_REMOTE_ROOT/volumes/$volume"
  if [ "$volume" != postgres-data ]; then
    tar -xzf "$backup/$volume.tar.gz" -C "$QM_REMOTE_ROOT/volumes/$volume"
  fi
done
"${compose[@]}" up -d db
for attempt in $(seq 1 30); do
  if docker exec quantmind-db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null; then break; fi
  sleep 2
done
tables=$(docker exec quantmind-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT count(*) FROM pg_tables WHERE schemaname = '\''public'\''"')
test "$tables" = 0 || { echo 'Target database is not empty; refusing overwrite.' >&2; exit 1; }
docker exec -i quantmind-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error --single-transaction' < "$backup/postgres.dump"
docker exec -i quantmind-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' \
  < deploy/table-counts.sql > "$backup/cloud-postgres-counts.txt"
cmp "$backup/postgres-counts.txt" "$backup/cloud-postgres-counts.txt"
# Written before any writer starts: a failure from here must NOT restart the Mac primary.
printf 'authority=lzy-vm\ncutover_utc=%s\nbackup=%s\n' "$(date -u +%FT%TZ)" "$backup" > "$QM_REMOTE_ROOT/AUTHORITY"
"${compose[@]}" up -d --no-build redis data-gateway rsshub huntly quantmind qwenpaw celery-worker celery-beat web
"${compose[@]}" ps
