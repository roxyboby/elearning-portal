#!/usr/bin/env bash
#
# safe_shutdown.sh — Gracefully stop the e-learning portal and optionally pause monitoring.
# - Works interactively with a menu (Shutdown / Reboot / Do nothing).
# - Supports --dry-run to preview actions (skips interactive menu).
# - Prompts to pause UptimeRobot monitor (uses ~/.ur_health.env).
#
# Env file format (~/.ur_health.env):
#   UR_API_KEY=uXXXX-XXXXXXXXXXXX
#   UR_MONITOR_ID=801162232
#   UR_MONITOR_NAME="elearning.wiabtech.in/healthz"
#
set -euo pipefail

# ------------------------- Config -------------------------
PRJ_DIR="$HOME/e_learning_portal"
LOG_DIR="$HOME/logs"
PORTS=("5000" "8000")        # Flask dev / Gunicorn prod
SVC_CANDIDATES=("cloudflared" "gunicorn" "nginx")
UR_ENV="$HOME/.ur_health.env"
UR_MARKER="$HOME/.ur_health.paused"

# ------------------------- Flags --------------------------
DRY_RUN=false
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY_RUN=true
fi

# ------------------------- Logging ------------------------
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/safe_shutdown_$(date +%F).log"
_ts() { date +"[%Y-%m-%d %H:%M:%S]"; }
log() { echo "$(_ts) $*" | tee -a "$LOG_FILE"; }
run() {
  if $DRY_RUN; then
    log "[DRY-RUN] $*"
  else
    eval "$@" | tee -a "$LOG_FILE"
  fi
}

# Ensure prompts always show up on the real terminal
prompt() {
  local msg="$1"
  printf "%s" "$msg" > /dev/tty
}

# ------------------------- Sudo keepalive -----------------
refresh_sudo() {
  if $DRY_RUN; then
    log "[DRY-RUN MODE ENABLED] No actions will be executed."
  fi
  if $DRY_RUN; then
    log "Refreshing sudo credentials (skipped in dry-run)…"
  else
    log "Refreshing sudo credentials…"
    sudo -v
  fi
}

# ------------------------- UptimeRobot helpers ------------
pause_ur_healthcheck() {
  if [[ ! -f "$UR_ENV" ]]; then
    log "No $UR_ENV found. Skipping UptimeRobot pause."
    return 0
  fi
  # shellcheck disable=SC1090
  source "$UR_ENV"
  if [[ -z "${UR_API_KEY:-}" || -z "${UR_MONITOR_ID:-}" ]]; then
    log "UR_API_KEY/UR_MONITOR_ID missing in $UR_ENV. Skipping UptimeRobot pause."
    return 0
  fi
  log "Pausing UptimeRobot monitor: ${UR_MONITOR_NAME:-$UR_MONITOR_ID} …"
  if $DRY_RUN; then
    log "[DRY-RUN] Would POST editMonitor status=0"
    : > "$UR_MARKER"
    return 0
  fi
  RESP=$(curl -sS -X POST https://api.uptimerobot.com/v2/editMonitor \
    -d "api_key=${UR_API_KEY}&id=${UR_MONITOR_ID}&status=0")
  if echo "$RESP" | grep -q '"stat":"ok"'; then
    log "Paused."
    : > "$UR_MARKER"
  else
    log "Warning: UptimeRobot pause failed: $RESP"
  fi
}

# ------------------------- Process helpers ----------------
kill_listeners_on_port() {
  local port="$1"
  local pids
  pids=$(sudo lsof -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    log "No process listening on port $port."
    return 0
  fi
  log "Killing processes on port $port…"
  log "$(sudo ss -ltnp | awk -v p=":$port" '$4 ~ p {print $0}')"
  if $DRY_RUN; then
    log "[DRY-RUN] Would kill PIDs: $pids"
  else
    sudo kill $pids || true
    sleep 1
    if sudo ss -ltnp | grep -q ":$port"; then
      log "Force killing remaining listeners on $port…"
      sudo fuser -k "${port}"/tcp || true
    fi
  fi
}

stop_services_if_present() {
  log "Stopping system services if present…"
  for svc in "${SVC_CANDIDATES[@]}"; do
    if systemctl list-unit-files --type=service | grep -q "^${svc}.service"; then
      if systemctl is-active --quiet "$svc"; then
        if $DRY_RUN; then
          log "[DRY-RUN] Would stop $svc.service"
        else
          sudo systemctl stop "$svc"
        fi
      else
        log "Service $svc installed but not active."
      fi
    else
      log "Service $svc not installed (skipping)."
    fi
    # Small wait between checks for cleaner logs
    sleep 1
  done
}

stop_manual_flask_gunicorn() {
  log "Stopping any manually started Flask/Gunicorn processes…"
  # Flask (dev server)
  local flask_pids
  flask_pids=$(pgrep -f "flask run" || true)
  if [[ -n "$flask_pids" ]]; then
    if $DRY_RUN; then
      log "[DRY-RUN] Would kill Flask PIDs: $flask_pids"
    else
      kill $flask_pids || true
    fi
  else
    log "No manual Flask run processes found."
  fi

  # Gunicorn started from project venv
  local g_pids
  g_pids=$(pgrep -af "gunicorn" | awk '{print $1}' || true)
  if [[ -n "$g_pids" ]]; then
    # Filter to our project dir only
    local ours
    ours=$(pgrep -af "gunicorn" | grep "$PRJ_DIR" | awk '{print $1}' || true)
    if [[ -n "$ours" ]]; then
      if $DRY_RUN; then
        log "[DRY-RUN] Would stop gunicorn from $PRJ_DIR…"
        pgrep -af "gunicorn" | grep "$PRJ_DIR" | tee -a "$LOG_FILE"
      else
        log "Stopping gunicorn from $PRJ_DIR…"
        pgrep -af "gunicorn" | grep "$PRJ_DIR" | tee -a "$LOG_FILE"
        kill $ours || true
      fi
    fi
  fi
}

sync_disks() {
  log "Syncing disks…"
  $DRY_RUN || sync
}

# ------------------------- Interactive menu ---------------
ask_choice() {
  while true; do
    echo
    echo "What next?"
    echo "  1) Shutdown (power off)"
    echo "  2) Reboot"
    echo "  3) Do nothing (just stop services)"
    printf "Choose [1/2/3]: " > /dev/tty

    if read -r -t 120 choice < /dev/tty; then
      case "$choice" in
        1)
          printf "Pause UptimeRobot health check until next boot? [y/N]: " > /dev/tty
          if read -r -t 60 yn < /dev/tty && [[ "${yn,,}" =~ ^(y|yes)$ ]]; then
            pause_ur_healthcheck
          else
            echo "Leaving UptimeRobot monitor as-is."
          fi
          $DRY_RUN && { log "[DRY-RUN] Would shutdown now."; return; }
          sudo shutdown -h now
          return
          ;;
        2)
          printf "Pause UptimeRobot health check until next boot? [y/N]: " > /dev/tty
          if read -r -t 60 yn < /dev/tty && [[ "${yn,,}" =~ ^(y|yes)$ ]]; then
            pause_ur_healthcheck
          else
            echo "Leaving UptimeRobot monitor as-is."
          fi
          $DRY_RUN && { log "[DRY-RUN] Would reboot now."; return; }
          sudo reboot
          return
          ;;
        3)
          printf "Pause UptimeRobot health check now (no shutdown)? [y/N]: " > /dev/tty
          if read -r -t 60 yn < /dev/tty && [[ "${yn,,}" =~ ^(y|yes)$ ]]; then
            pause_ur_healthcheck
          else
            echo "Leaving UptimeRobot monitor as-is."
          fi
          log "Done. Services stopped. System left running."
          return
          ;;
        *)
          echo "Invalid choice. Please enter 1, 2, or 3."
          ;;
      esac
    else
      echo "No input received in 120s. Defaulting to Shutdown (1)."
      printf "Pause UptimeRobot health check until next boot? [y/N]: " > /dev/tty
      if read -r -t 60 yn < /dev/tty && [[ "${yn,,}" =~ ^(y|yes)$ ]]; then
        pause_ur_healthcheck
      else
        echo "Leaving UptimeRobot monitor as-is."
      fi
      $DRY_RUN && { log "[DRY-RUN] Would shutdown now."; return; }
      sudo shutdown -h now
      return
    fi
  done
}

# ------------------------- Main ---------------------------
main() {
  log "Starting safe shutdown sequence…"
  log "Logs: $LOG_FILE"

  refresh_sudo

  log "Gracefully stopping app ports…"
  for p in "${PORTS[@]}"; do
    kill_listeners_on_port "$p"
  done

  stop_services_if_present
  stop_manual_flask_gunicorn
  sync_disks
  echo | tee -a "$LOG_FILE"

  if $DRY_RUN; then
    # Summarize
    log "======================= DRY-RUN SUMMARY ========================"
    {
      echo -n "Ports detected :"
      for p in "${PORTS[@]}"; do
        if ss -ltnp | grep -q ":$p"; then echo -n " $p"; fi
      done
      echo
      echo -n "Svc installed  : "
      for s in "${SVC_CANDIDATES[@]}"; do
        systemctl list-unit-files --type=service | grep -q "^${s}.service" && echo -n "$s " || true
      done
      echo
      echo -n "Svc active     : "
      for s in "${SVC_CANDIDATES[@]}"; do
        systemctl is-active --quiet "$s" && echo -n "$s " || true
      done
      echo
      echo "Flask procs:"
      pgrep -af "flask run" || echo "  None"
      echo "Gunicorn procs:"
      pgrep -af "gunicorn" || echo "  None"
      echo "==============================================================="
      echo "DRY-RUN complete. No actions executed."
    } | tee -a "$LOG_FILE"
    return 0
  fi

  # Interactive menu
  ask_choice
}

main "$@"
