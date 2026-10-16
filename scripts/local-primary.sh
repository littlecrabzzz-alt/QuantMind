#!/usr/bin/env bash
# Mac business primary; never reuse the legacy authority or sandbox volumes.
set -euo pipefail
if [ "${QM_SCRIPT_TEXT:-}" != "$0" ]; then
  export QM_SCRIPT_TEXT="$0"
  exec bash -c "$(< "$0")" "$0" "$@"
fi
umask 077
PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
STATE="$PROJECT/.local-primary"
export QM_PRIMARY_PROJECT="$PROJECT"
export QM_PRIMARY_STATE="$STATE/project"
COMPOSE=(docker compose --project-name quantmind-local --env-file "$PROJECT/.env.local" -f "$PROJECT/docker-compose.yml" -f "$PROJECT/deploy/compose.local-primary.yml" --project-directory "$PROJECT")
LOCK="$PROJECT/logs/local-primary.lock"
ROLLBACK=none
NEW_VOLUMES=()
SERVICES=()
LABEL=com.quantmind.local-primary
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

fail() { echo "$*" >&2; exit 1; }
require_mac() {
  [ "$(uname -s)" = Darwin ] || fail 'local-primary is Mac-only.'
  [ -z "${DOCKER_HOST:-}" ] || fail 'Unset DOCKER_HOST; use local Docker Desktop.'
  local endpoint
  endpoint=$(docker context inspect --format '{{.Endpoints.docker.Host}}')
  case "$endpoint" in
    "unix://$HOME/.docker/"*|unix:///var/run/docker.sock) ;;
    *) fail "Refusing non-local Docker endpoint: $endpoint" ;;
  esac
}
require_docker() {
  [ -f "$PROJECT/.env.local" ] || fail 'Missing .env.local.'
  [ "$(docker info --format '{{.OperatingSystem}}')" = 'Docker Desktop' ] || fail 'Expected local Docker Desktop daemon.'
}
cleanup() {
  local rc=$? volume
  trap - EXIT INT TERM
  set +e
  if [ "$ROLLBACK" = adopt ]; then
    # Preflight refused ALL pre-existing primary containers and volumes.
    if "${COMPOSE[@]}" --profile research --profile research-agent down; then
      for volume in "${NEW_VOLUMES[@]}"; do
        docker volume rm "$volume" || echo "Could not remove new volume $volume; inspect before retrying." >&2
      done
      rm -rf "$STATE"
    else
      echo 'Could not stop the failed adoption; retain its files for recovery.' >&2
    fi
  elif [ "$ROLLBACK" = start ]; then
    "${COMPOSE[@]}" stop "${SERVICES[@]}"
    echo 'Failed start stopped; volumes retained, cloud tunnel remains disabled.' >&2
  fi
  rm -f "$LOCK/pid"
  rmdir "$LOCK"
  exit "$rc"
}
lock_operation() {
  mkdir -p "$PROJECT/logs"
  mkdir "$LOCK" 2>/dev/null || fail "Another operation owns $LOCK; inspect its pid before removing a stale lock."
  trap cleanup EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  echo "$$" > "$LOCK/pid"
}
refuse_sandbox() {
  [ -z "$(docker ps -q --filter label=com.docker.compose.project=quantmind-dev)" ] || fail 'Local-dev sandbox is running; stop it before using the primary.'
  [ ! -d "$PROJECT/logs/local-dev.lock" ] || fail 'A local-dev operation is in progress.'
}
healthy() { curl --noproxy '*' --connect-timeout 2 --max-time 3 -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; }

adopt() {
  local snapshot item volumes containers
  [ "$#" -eq 1 ] || fail 'Usage: scripts/local-primary.sh adopt <snapshot_dir>'
  snapshot=$(cd "$1" && pwd -P)
  [ -f "$snapshot/COMPLETE" ] || fail 'Snapshot is not complete.'
  python3 - "$PROJECT" "$snapshot" <<'PY_VERIFY'
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import dual_node_snapshot as snapshot
root = Path(sys.argv[2])
verification = snapshot.verify_snapshot(root)
cold = root / "COLD_BACKUP.json"
snapshot.require(cold.name in verification["checksums"],
                 "Adopt only the final, hashed cold-backup snapshot")
snapshot.require(json.loads(cold.read_text()).get("automatic_writers_disabled") is True,
                 "Cloud writer auto-start has not been disabled")
snapshot.verify_cloud_frozen(root)
PY_VERIFY
  [ ! -e "$STATE" ] && [ ! -L "$STATE" ] || fail 'Local primary already exists; refusing to overwrite it.'
  refuse_sandbox
  containers=$(docker ps -aq --filter label=com.docker.compose.project=quantmind-local)
  [ -z "$containers" ] || fail 'Existing quantmind-local containers; inspect them before adopting.'
  volumes=$(docker volume ls --format '{{.Name}}')
  for item in postgres-data redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
    ! echo "$volumes" | grep -Fxq "quantmind-local_$item" || fail "Existing primary volume: quantmind-local_$item"
  done
  for item in postgres.dump runtime-manifest.jsonl redis-data.tar.gz qwenpaw-data.tar.gz qwenpaw-secrets.tar.gz qwenpaw-backups.tar.gz qwenpaw-shared.tar.gz; do
    [ -f "$snapshot/$item" ] || fail "Missing snapshot file: $item"
  done
  [ -d "$snapshot/project/data" ] || fail 'Missing snapshot runtime project.'
  mkdir "$STATE"
  ROLLBACK=adopt
  # APFS copy-on-write, falling back to a normal copy on other filesystems.
  cp -cR "$snapshot/project" "$QM_PRIMARY_STATE" || cp -R "$snapshot/project/." "$QM_PRIMARY_STATE/"
  for item in data db models logs results user_pools_local; do mkdir -p "$QM_PRIMARY_STATE/$item"; done
  # Keep the adopted baseline independent of later snapshot rotation.
  cp "$snapshot/runtime-manifest.jsonl" "$STATE/runtime-manifest.jsonl"
  for item in postgres-data redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
    NEW_VOLUMES+=("quantmind-local_$item")
    docker volume create --label com.docker.compose.project=quantmind-local --label "com.docker.compose.volume=$item" "quantmind-local_$item" >/dev/null
  done
  for item in redis-data qwenpaw-data qwenpaw-secrets qwenpaw-backups qwenpaw-shared; do
    docker run --rm -v "quantmind-local_$item:/target" -v "$snapshot:/snapshot:ro" \
      postgres:15-alpine sh -c 'tar -xzf "/snapshot/$1.tar.gz" -C /target' sh "$item"
  done
  "${COMPOSE[@]}" up -d db
  for _ in {1..60}; do
    [ "$(docker inspect -f '{{.State.Health.Status}}' quantmind-local-db 2>/dev/null || true)" = healthy ] && break
    sleep 2
  done
  [ "$(docker inspect -f '{{.State.Health.Status}}' quantmind-local-db)" = healthy ] || fail 'PostgreSQL did not become healthy.'
  docker exec -i quantmind-local-db sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error --single-transaction' < "$snapshot/postgres.dump"
  python3 - "$PROJECT" "$snapshot" "$STATE" <<'PY_RESTORE'
from pathlib import Path
import sys
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import dual_node_snapshot as snapshot
source, state = map(Path, sys.argv[2:])
snapshot.require(snapshot.manifest(state / "project", scope=snapshot.snapshot_scope(source))
                 == (source / "runtime-manifest.jsonl").read_text(),
                 "Adopted runtime copy differs from verified snapshot")
snapshot.verify_restored_database(source, "quantmind-local-db", state / "RESTORE_VERIFIED.json")
PY_RESTORE
  "${COMPOSE[@]}" down
  python3 - "$STATE" "$snapshot" "$PROJECT" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
state, snapshot, project = map(Path, sys.argv[1:])
sys.path.insert(0, str(project / "scripts"))
import dual_node_snapshot as snapshot_tools
cloud_verification = snapshot_tools.verify_cloud_frozen(snapshot)
(state / 'AUTHORITY.json').write_text(json.dumps({
    'snapshot_id': snapshot.name,
    'adopted_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    'source': 'cloud-cold-backup',
    'cold_backup': json.loads((snapshot / 'COLD_BACKUP.json').read_text()),
    'restore_verification': json.loads((state / 'RESTORE_VERIFIED.json').read_text()),
    'cloud_freeze_verification': cloud_verification,
}, indent=2) + '\n')
(state / 'READY').touch()
PY
  ROLLBACK=none
  echo 'Local primary adopted. Use start when ready to take over port 8000.'
}

start_primary() {
  local running service
  [ -f "$STATE/READY" ] && [ -s "$STATE/AUTHORITY.json" ] || fail 'Adopt a complete snapshot first.'
  refuse_sandbox
  python3 - "$STATE" <<'PY_CHECK'
import json
from pathlib import Path
import sys
authority = json.loads((Path(sys.argv[1]) / 'AUTHORITY.json').read_text())
if (authority.get('source') != 'cloud-cold-backup'
        or not authority.get('restore_verification')
        or not authority.get('cloud_freeze_verification')):
    raise SystemExit('Missing verified final handover; refusing local authority.')
for name in ('QUANTDB_SYNC.json', 'BC_SYNC.json'):
    path = Path(sys.argv[1]) / name
    if path.exists() and json.loads(path.read_text()).get('status') == 'files_applied':
        raise SystemExit('Market derivation is incomplete; let market-source recover before starting.')
PY_CHECK
  SERVICES=(db redis quantmind celery-worker celery-beat data-gateway huntly rsshub qwenpaw web)
  # A historic research/settings.json is not authorization to resume experiments.
  running=$("${COMPOSE[@]}" ps --status running --services)
  if [ -n "$running" ]; then
    for service in "${SERVICES[@]}"; do
      echo "$running" | grep -Fxq "$service" || fail 'Primary is partially running; inspect status before restarting.'
    done
    healthy || fail 'Existing primary API is unhealthy.'
    echo 'Local primary is already running.'
    return
  fi
  # Disable both old cloud transports persistently. A failed primary start must
  # never reconnect writes or refresh the authoritative local store from cloud.
  for service in com.quantmind.cloud-tunnel com.quantmind.snapshot-pull; do
    launchctl disable "gui/$(id -u)/$service"
    if launchctl print "gui/$(id -u)/$service" >/dev/null 2>&1; then
      launchctl bootout "gui/$(id -u)/$service"
    fi
    local legacy_plist="$HOME/Library/LaunchAgents/$service.plist"
    if [ -f "$legacy_plist" ]; then
      [ ! -e "$legacy_plist.disabled-local-primary" ] || fail 'Cloud transport backup already exists; inspect both plists.'
      mv "$legacy_plist" "$legacy_plist.disabled-local-primary"
    fi
  done
  for _ in {1..10}; do
    ! lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 && break
    sleep 1
  done
  ! lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || fail 'Port 8000 belongs to another process.'
  ROLLBACK=start
  "${COMPOSE[@]}" up -d db redis
  # Preserve old broker queues verbatim; never let a restored backlog silently
  # launch cancelled research or historical backtests.
  "${COMPOSE[@]}" run --rm --no-deps --entrypoint python quantmind \
    scripts/local_primary_broker_guard.py --output /data/local-primary/BROKER_GUARD.json
  "${COMPOSE[@]}" up -d "${SERVICES[@]}"
  for _ in {1..90}; do healthy && break; sleep 2; done
  healthy || fail 'Local API health check failed.'
  ROLLBACK=none
  echo 'Local primary ready: http://127.0.0.1:8000 (API), http://127.0.0.1:3080 (web).'
}

install_runtime() {
  [ "$#" -eq 2 ] || fail 'Usage: scripts/local-primary.sh install-runtime <new_Library_runtime_dir> <Library_artifact_root>'
  python3 - "$PROJECT" "$1" "$2" <<'PY_INSTALL_RUNTIME'
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys

source = Path(sys.argv[1]).resolve(strict=True)
managed = Path.home().resolve() / "Library/Application Support/QuantMind"
base = managed.resolve(strict=True)
if base != managed:
    raise SystemExit("Managed Library root must not redirect outside its real location")
requested = Path(sys.argv[2]).expanduser()
if os.path.lexists(requested):
    raise SystemExit("Runtime destination already exists; choose a new directory")
runtime = requested.resolve()
artifacts = Path(sys.argv[3]).expanduser().resolve(strict=True)
if (runtime == base or not runtime.is_relative_to(base)
        or not artifacts.is_relative_to(base) or not artifacts.is_dir()
        or artifacts == runtime or artifacts.is_relative_to(runtime) or runtime.is_relative_to(artifacts)):
    raise SystemExit("Runtime and artifact roots must be distinct real directories inside the managed Library root")

def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])

if Path(os.fsdecode(git(source, "rev-parse", "--show-toplevel")).strip()).resolve() != source:
    raise SystemExit("Install only from the source checkout, not another managed snapshot")
commit = git(source, "rev-parse", "HEAD").decode().strip()
roots = {"backend", "scripts", "deploy", "docker", "config", "strategy_templates", "docs", "requirements",
         "alphaagent", "TradingAgents-astock"}
root_files = {"docker-compose.yml", ".dockerignore", "pyproject.toml"}
dependencies = {"node_modules", ".venv", "venv", "env", ".git", ".hg", ".svn", "site-packages",
                "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "rd-agent"}
runtime_roots = {"data", "db", "models", "logs", "output", "results", "user_pools_local", "user_strategies",
                 ".local-primary", ".local-dev"}
data_suffixes = {".pyc", ".pyo", ".log", ".jsonl", ".parquet", ".arrow", ".feather",
                 ".sqlite", ".sqlite3", ".db", ".pt", ".pth", ".onnx", ".safetensors", ".pkl", ".pickle",
                 ".ckpt", ".bin", ".whl", ".egg", ".so", ".dylib"}
policy = re.compile(r"^(?:agents|claude|gemini)(?:[._-]|$)", re.IGNORECASE)

def allowed(path):
    parts = path.parts
    if (not parts or path.is_absolute() or ".." in parts
            or any(part in dependencies or policy.match(part.lstrip(".")) for part in parts)
            or path.suffix.lower() in data_suffixes):
        return False
    if parts[0] in ("alphaagent", "TradingAgents-astock") and len(parts) > 1 and parts[1] in runtime_roots:
        return False
    if len(parts) > 1 and parts[:2] == ("backend", "scratch"):
        return False
    if path.name.startswith(".env") and not path.name.endswith(".example"):
        return False
    return True

def tracked(root):
    return {Path(os.fsdecode(name)) for name in git(root, "ls-files", "--cached", "-z").split(b"\0") if name}

selected = {path for path in tracked(source) if allowed(path) and
            (path.parts[0] in roots or str(path) in root_files
             or len(path.parts) == 1 and path.name.startswith("requirements"))}
nested = {}
for name in ("alphaagent", "TradingAgents-astock"):
    repository = source / name
    if (repository / ".git").exists():
        if Path(os.fsdecode(git(repository, "rev-parse", "--show-toplevel")).strip()).resolve() != repository.resolve():
            raise SystemExit("Nested source repository has an unexpected root: " + name)
        selected = {path for path in selected if path.parts[0] != name}
        selected.update(Path(name) / path for path in tracked(repository) if allowed(Path(name) / path))
        nested[name] = git(repository, "rev-parse", "HEAD").decode().strip()

def add_tree(relative):
    tree = source / relative
    if not tree.is_dir() or tree.is_symlink():
        raise SystemExit("Required source directory missing or linked: " + str(relative))
    for directory, children, files in os.walk(tree, followlinks=False):
        parent = Path(directory)
        retained = []
        for child in children:
            path = (parent / child).relative_to(source)
            if allowed(path):
                if (parent / child).is_symlink():
                    raise SystemExit("Source directory symlink is not a portable snapshot: " + str(path))
                retained.append(child)
        children[:] = retained
        selected.update((parent / name).relative_to(source) for name in files
                        if allowed((parent / name).relative_to(source)))

add_tree(Path("vendor/ashare-lab/src"))
add_tree(Path("electron/dist-react"))
vendor_files = {Path("vendor/ashare-lab") / name
                for name in ("frozen-source.json", "frozen-data.json", "requirements.txt")}
private = {Path(".env.local"), Path("config/runtime.env")}
selected.update(vendor_files | private)
required = vendor_files | private | {Path(name) for name in
    ("docker-compose.yml", ".dockerignore", "requirements.txt", "backend/main_oss.py",
     "scripts/local-primary.sh", "deploy/compose.local-primary.yml", "electron/dist-react/index.html")}
if not required.issubset(selected):
    raise SystemExit("Required runtime code is not tracked/staged in the source checkout")
for path in required:
    if not (source / path).is_file() or (source / path).is_symlink():
        raise SystemExit("Required runtime file missing or linked: " + str(path))
for name in ("data", "reports"):
    if not (artifacts / "ashare-takeover/trees/ashare-lab" / name).is_dir():
        raise SystemExit("Artifact archive is missing vendor " + name)

runtime.parent.mkdir(parents=True, exist_ok=True)
runtime.mkdir(mode=0o700)
files, links = {}, {}
for relative in sorted(selected):
    original = source / relative
    if not os.path.lexists(original):
        continue  # A tracked worktree deletion is not deployed from its stale index blob.
    resolved = original.resolve(strict=True)
    if not resolved.is_relative_to(source) or resolved.relative_to(source) not in selected:
        raise SystemExit("Source path escapes the selected code snapshot: " + str(relative))
    target = runtime / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if original.is_symlink():
        link = os.path.relpath(runtime / resolved.relative_to(source), target.parent)
        target.symlink_to(link)
        encoded = os.fsencode(link)
        links[str(relative)] = {"target": link, "size": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}
    elif stat.S_ISREG(original.stat().st_mode):
        shutil.copyfile(original, target)
        target.chmod(0o600 if relative in private else 0o755 if original.stat().st_mode & 0o111 else 0o644)
        value = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                value.update(block)
        files[str(relative)] = {"sha256": value.hexdigest(), "size": target.stat().st_size,
                                "mode": stat.S_IMODE(target.stat().st_mode)}
    else:
        raise SystemExit("Refusing non-regular source file: " + str(relative))
for relative, link in (("output", str(artifacts)),
                       ("vendor/ashare-lab/data", "../../output/ashare-takeover/trees/ashare-lab/data"),
                       ("vendor/ashare-lab/reports", "../../output/ashare-takeover/trees/ashare-lab/reports")):
    target = runtime / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(link)
    encoded = os.fsencode(link)
    links[relative] = {"target": link, "size": len(encoded), "sha256": hashlib.sha256(encoded).hexdigest()}
manifest = {"schema_version": 1, "source_project": str(source), "source_commit": commit,
            "source_selection": "Git tracked/staged names; copied current worktree bytes",
            "nested_repositories": nested, "runtime_project": str(runtime), "artifact_root": str(artifacts),
            "installed_at": datetime.now(timezone.utc).isoformat(), "files": files, "links": links}
encoded = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
manifest_path = runtime / "MAIN_CODE_MANIFEST.json"
manifest_path.write_bytes(encoded)
manifest_path.chmod(0o600)
print(json.dumps({"runtime_project": str(runtime), "manifest": str(manifest_path),
                  "manifest_sha256": hashlib.sha256(encoded).hexdigest(),
                  "files": len(files), "bytes": sum(item["size"] for item in files.values())}))
PY_INSTALL_RUNTIME
}

install_autostart() {
  [ -f "$STATE/READY" ] || fail 'Adopt before installing autostart.'
  mkdir -p "$HOME/Library/LaunchAgents"
  python3 - "$PROJECT" "$PLIST" <<'PY'
import plistlib
from pathlib import Path
import sys
project, target = map(Path, sys.argv[1:])
definition = plistlib.loads((project / 'deploy/com.quantmind.local-primary.plist').read_bytes())
for key in ('WorkingDirectory', 'StandardOutPath', 'StandardErrorPath'):
    definition[key] = definition[key].replace('__PROJECT__', str(project))
definition['ProgramArguments'] = [v.replace('__PROJECT__', str(project)) for v in definition['ProgramArguments']]
target.write_bytes(plistlib.dumps(definition))
PY
  if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then launchctl bootout "gui/$(id -u)/$LABEL"; fi
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
}

# This file-only operation does not inspect Docker or create adoption/autostart state.
if [ "${1:-}" = install-runtime ]; then
  shift
  install_runtime "$@"
  exit
fi

require_mac
case "${1:-help}" in
  adopt) require_docker; lock_operation; shift; adopt "$@" ;;
  start)
    # Login can precede Docker Desktop readiness.
    if [ "${QM_PRIMARY_AUTOSTART:-}" = 1 ]; then
      open -g -a Docker
      for _ in {1..60}; do docker info >/dev/null 2>&1 && break; sleep 2; done
      for _ in {1..15}; do [ -d "$LOCK" ] || break; sleep 1; done
    fi
    require_docker; lock_operation; start_primary ;;
  stop)
    require_docker; lock_operation
    "${COMPOSE[@]}" --profile research --profile research-agent down
    echo 'Local primary stopped; volumes retained, cloud tunnel remains disabled.' ;;
  status)
    require_docker
    "${COMPOSE[@]}" --profile research --profile research-agent ps
    if [ -f "$STATE/AUTHORITY.json" ]; then cat "$STATE/AUTHORITY.json"; else echo 'Not adopted.'; fi
    lsof -nP -iTCP:8000 -sTCP:LISTEN || true ;;
  install-autostart) lock_operation; install_autostart ;;
  uninstall-autostart)
    lock_operation
    if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then launchctl bootout "gui/$(id -u)/$LABEL"; fi
    rm -f "$PLIST" ;;
  *) echo 'Usage: scripts/local-primary.sh {install-runtime <new_Library_runtime_dir> <Library_artifact_root>|adopt <snapshot_dir>|start|stop|status|install-autostart|uninstall-autostart}'; exit 2 ;;
esac
