#!/bin/bash
# Stop Cloudflare Tunnel + Gunicorn in one go.
# Works whether started manually or via systemd.
set -euo pipefail

PRJ="/home/roland/e_learning_portal"

log() { printf "[%s] %s\n" "$(date +'%F %T')" "$*"; }

stop_systemd() {
  local svc="$1"
  if systemctl list-unit-files --type=service | grep -q "^${svc}.service"; then
    if systemctl is-active --quiet "$svc"; then
      log "Stopping systemd service: $svc"
      sudo systemctl stop "$svc"
    else
      log "Service $svc installed but not active."
    fi
  else
    log "Service $svc not installed."
  fi
}

kill_user_proc() {
  local pattern="$1"
  if pgrep -fa "$pattern" >/dev/null 2>&1; then
    log "Killing processes matching: $pattern"
    pkill -f "$pattern" || true
  else
    log "No processes matching: $pattern"
  fi
}

free_port() {
  local port="$1"
  if ss -ltnp | grep -q ":$port"; then
    log "Freeing TCP port $port"
    sudo fuser -k "${port}"/tcp || true
  else
    log "No listener on port $port"
  fi
}

log "Stopping portal…"

# 1) Try systemd services first (if you later enable them)
stop_systemd cloudflared
stop_systemd gunicorn

# 2) Kill any manually started processes (start_portal.sh style)
kill_user_proc "/usr/bin/cloudflared tunnel"
kill_user_proc "$PRJ/venv/bin/gunicorn"

# 3) Free common dev ports (safety net)
free_port 8000
free_port 5000

# 4) Show what’s left (should be empty for our ports)
log "Remaining listeners on 8000/5000:"
ss -ltnp | egrep ':8000|:5000' || echo "  none"

log "Done."
