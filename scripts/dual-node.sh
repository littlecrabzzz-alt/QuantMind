#!/usr/bin/env bash
# Run from either checkout. No --delete: retries never remove unique research.
set -euo pipefail
# Read once: Syncthing/editor updates must not change a running shell's file offset.
if [ "${QM_SCRIPT_TEXT:-}" != "$0" ]; then
  export QM_SCRIPT_TEXT="$0"
  exec bash -c "$(< "$0")" "$0" "$@"
fi
PROJECT=$(cd "$(dirname "$0")/.." && pwd -P)
source "$PROJECT/deploy/dual-node.env"
cd "$PROJECT"
umask 077
RSYNC=rsync
[ ! -x /opt/homebrew/bin/rsync ] || RSYNC=/opt/homebrew/bin/rsync

cloud_guard() {
  ssh -o BatchMode=yes "$QM_SSH_TARGET" "sudo -n bash -c 'set -eu; test \"\$(findmnt -n -o UUID -T $QM_REMOTE_ROOT)\" = $QM_DISK_UUID; test -d $QM_REMOTE_PROJECT; test ! -e $QM_REMOTE_ROOT/AUTHORITY'"
}

case "${1:-help}" in
  handoff)
    shift
    exec python3 scripts/dual_node_check.py "$@"
    ;;
  snapshot-refresh)
    [ "$(uname -s)" = Darwin ]
    python3 scripts/dual_node_check.py
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$QM_SSH_TARGET" "sudo -n python3 $QM_REMOTE_PROJECT/scripts/dual_node_snapshot.py create"
    python3 scripts/dual_node_snapshot.py pull
    python3 scripts/dual_node_check.py
    ;;
  install-mac-guard)
    [ "$(uname -s)" = Darwin ]
    ssh "$QM_SSH_TARGET" "sudo -n test -f $QM_REMOTE_ROOT/AUTHORITY"
    if [ -e docker-compose.override.yml ] && ! cmp -s deploy/compose.mac-client.yml docker-compose.override.yml; then
      echo 'Existing local Compose override differs; refusing to overwrite it.' >&2
      exit 1
    fi
    install -m 0644 deploy/compose.mac-client.yml docker-compose.override.yml
    ;;
  install-tunnel)
    # Only after cutover: never take port 8000 away from the original Mac service.
    [ "$(uname -s)" = Darwin ]
    ssh "$QM_SSH_TARGET" "sudo -n test -f $QM_REMOTE_ROOT/AUTHORITY"
    ssh "$QM_SSH_TARGET" 'curl -fsS http://127.0.0.1:18000/health >/dev/null'
    label=com.quantmind.cloud-tunnel
    plist="$HOME/Library/LaunchAgents/$label.plist"
    if ! launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
      for port in 8000 18080; do
        if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
          echo "Local port $port is still in use; refusing to replace that service." >&2
          exit 1
        fi
      done
    else
      launchctl bootout "gui/$(id -u)/$label"
    fi
    mkdir -p "$HOME/Library/LaunchAgents"
    [ ! -f "$plist" ] || cp -p "$plist" "$PROJECT/logs/cloud-tunnel.previous.plist"
    install -m 0644 deploy/com.quantmind.cloud-tunnel.plist "$plist"
    launchctl bootstrap "gui/$(id -u)" "$plist"
    ;;
  web-publish)
    npm run build:react --workspace=electron
    # The script protects secrets with umask 077, but nginx must read public assets.
    chmod -R u=rwX,go=rX electron/dist-react
    release="$QM_REMOTE_ROOT/staging/web-$(date -u +%Y%m%dT%H%M%SZ)"
    ssh "$QM_SSH_TARGET" "sudo -n mkdir -p $release"
    "$RSYNC" -a --compress --rsync-path='sudo -n rsync' electron/dist-react/ "$QM_SSH_TARGET:$release/"
    ssh "$QM_SSH_TARGET" "sudo -n bash -c 'set -eu; if test -d $QM_REMOTE_PROJECT/electron/dist-react; then mv $QM_REMOTE_PROJECT/electron/dist-react $release.previous; fi; mv $release $QM_REMOTE_PROJECT/electron/dist-react; if docker container inspect quantmind-web >/dev/null 2>&1; then cd $QM_REMOTE_PROJECT; bash scripts/dual-node.sh cloud-compose up -d --force-recreate web; fi'"
    ;;
  connect)
    # Same web service, same authoritative database, encrypted SSH transport.
    exec ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
      -L 127.0.0.1:18080:127.0.0.1:"$QM_WEB_PORT" "$QM_SSH_TARGET"
    ;;
  images)
    # Reuse the exact tested amd64 environments; no cross-architecture volumes.
    for image in quantmind-oss:latest quantmind-qwenpaw:local; do
      [ "$(docker image inspect "$image" --format '{{.Architecture}}')" = amd64 ]
    done
    docker image save quantmind-oss:latest quantmind-qwenpaw:local | gzip -1 | \
      ssh -o BatchMode=yes "$QM_SSH_TARGET" 'gunzip | sudo -n docker image load'
    ;;
  preseed)
    # Only valid before cutover. Copy directly to the idle target: no second 65GB tree.
    cloud_guard
    paths=(data db models)
    for path in results* user_pools_local; do
      [ ! -d "$path" ] || paths+=("$path")
    done
    "$RSYNC" -a --no-owner --no-group --partial --partial-dir=.rsync-partial \
      --compress --stats --exclude='.DS_Store' --exclude='data/upgrade_v*.sql' \
      --exclude='data/stocks/' --exclude='db/sql/' \
      --rsync-path='sudo -n rsync' -e 'ssh -o BatchMode=yes -o ServerAliveInterval=30' \
      "${paths[@]}" "$QM_SSH_TARGET:$QM_REMOTE_PROJECT/"
    ;;
  cloud-compose)
    [ "$(id -u)" = 0 ] || { echo 'Run as root on lzy-vm.' >&2; exit 1; }
    [ "$(findmnt -n -o UUID -T "$QM_REMOTE_ROOT")" = "$QM_DISK_UUID" ]
    shift
    exec docker compose --env-file .env.local -f docker-compose.yml \
      -f deploy/compose.cloud.yml --project-directory "$PROJECT" "$@"
    ;;
  status)
    ssh -o BatchMode=yes "$QM_SSH_TARGET" "sudo -n bash -c 'df -h $QM_REMOTE_ROOT; test ! -f $QM_REMOTE_ROOT/AUTHORITY || cat $QM_REMOTE_ROOT/AUTHORITY; cd $QM_REMOTE_PROJECT; bash scripts/dual-node.sh cloud-compose ps'"
    ;;
  *)
    echo 'Usage: bash scripts/dual-node.sh {handoff [--align-git mac|cloud]|snapshot-refresh|preseed|images|web-publish|install-mac-guard|install-tunnel|connect|cloud-compose <args...>|status}'
    exit 2
    ;;
esac
