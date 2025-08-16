#!/usr/bin/env bash
set -euo pipefail

PRJ="${PRJ:-$HOME/e_learning_portal}"
BIND_IP="${BIND_IP:-192.168.1.216}"
PORT="${PORT:-8000}"
LOG="${LOG:-/tmp/portal_watch.log}"
TUNNEL_NAME="${TUNNEL_NAME:-elearning-pi}"
LOCK="${LOCK:-/tmp/portal_watch.lock}"

STATE_DIR="/tmp/portal_watch.state"
mkdir -p "$STATE_DIR"
FAIL_STATE="${STATE_DIR}/previous_fail"
COOLDOWN_FILE="${STATE_DIR}/cooldown"
RESTART_WINDOW_FILE="${STATE_DIR}/restart_window"
COOLDOWN_SECS="${COOLDOWN_SECS:-120}"
RESTART_CAP_WINDOW="${RESTART_CAP_WINDOW:-600}"
RESTART_CAP_COUNT="${RESTART_CAP_COUNT:-2}"

timestamp(){ date +'%F %T'; }
log(){ echo "[$(timestamp)] $*" >> "$LOG"; }

exec 9>"$LOCK"
if ! flock -n 9; then
  log "skip: watchdog already running"
  exit 0
fi

if [[ -f "$COOLDOWN_FILE" ]]; then
  now=$(date +%s); last=$(stat -c %Y "$COOLDOWN_FILE" 2>/dev/null || echo 0)
  if (( now - last < COOLDOWN_SECS )); then
    log "cooldown: skipping checks"
    exit 0
  fi
fi

reset_or_increment_cap() {
  local now=$(date +%s)
  local start=0 count=0
  if [[ -f "$RESTART_WINDOW_FILE" ]]; then
    read -r start count < "$RESTART_WINDOW_FILE" || true
  fi
  if (( now - start > RESTART_CAP_WINDOW )); then
    echo "$now 0" > "$RESTART_WINDOW_FILE"
    count=0
  fi
  echo "$start ${count:-0}"
}

increment_cap() {
  local now=$(date +%s)
  local start=0 count=0
  read -r start count < "$RESTART_WINDOW_FILE" || true
  echo "$start $((count+1))" > "$RESTART_WINDOW_FILE"
}

cap_ok(){
  read -r start count <<< "$(reset_or_increment_cap)"
  if (( count >= RESTART_CAP_COUNT )); then
    log "restart cap reached (${count}/${RESTART_CAP_COUNT}) — pausing until window resets"
    return 1
  fi
  return 0
}

app_ok=0 tunnel_pid=0 tunnel_ready=0

curl -fsS --max-time 5 "http://${BIND_IP}:${PORT}/healthz" >/dev/null 2>&1 && app_ok=1
[[ $app_ok -eq 1 ]] && log "healthz OK" || log "healthz FAIL"

if pgrep -f "/usr/bin/cloudflared tunnel --config .* run ${TUNNEL_NAME}" >/dev/null; then
  tunnel_pid=1
  log "cloudflared PID OK"
else
  log "cloudflared MISSING"
fi

for _ in 1 2 3; do
  if cloudflared tunnel info "${TUNNEL_NAME}" 2>/dev/null | grep -q '^CONNECTOR ID'; then
    tunnel_ready=1
    break
  fi
  sleep 10
done
[[ $tunnel_ready -eq 1 ]] && log "tunnel connectors OK" || log "tunnel connectors MISSING"

this_run_fail=0
if [[ $app_ok -eq 0 && $tunnel_ready -eq 0 ]]; then
  this_run_fail=1
fi

if [[ $this_run_fail -eq 1 ]]; then
  if [[ -f "$FAIL_STATE" ]]; then
    log "two-strike failure confirmed — considering restart"
    if cap_ok; then
      log "restarting via portalctl…"
systemd-run --user --quiet --collect --unit=portalctl-restart \
  "${PRJ}/portalctl" restart >> "$LOG" 2>&1 || true
      : > "$COOLDOWN_FILE"
      increment_cap
      rm -f "$FAIL_STATE"
    else
      log "restart suppressed due to cap"
    fi
  else
    log "first-strike failure (will require one more failing run)"
    : > "$FAIL_STATE"
  fi
else
  [[ -f "$FAIL_STATE" ]] && rm -f "$FAIL_STATE"
fi

awk 'NR<=1200{print} NR>1200{exit}' "$LOG" 2>/dev/null > "${LOG}.tmp" || true
mv -f "${LOG}.tmp" "$LOG" 2>/dev/null || true
