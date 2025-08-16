#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="/home/roland/e_learning_portal"
LOCAL_DIR="$PROJECT/backups"
USB_DIR="/mnt/backup_usb/e_learning_portal"

SOURCE="auto"   # prefer USB if mounted & has backups; else local
DRY_RUN=false
PREVIEW=false
PORT=9000

# ---- Helpers ----------------------------------------------------------------
latest_archive() {
  # echo "<path> <basename> <mtime>"
  local d="$1"
  [[ -d "$d" ]] || { echo ""; return; }
  local f
  f="$(ls -1t "$d"/backup_*.tar.gz 2>/dev/null | head -1 || true)"
  [[ -n "$f" ]] || { echo ""; return; }
  local b ts
  b="$(basename "$f")"
  # mtime in a readable form; fall back if stat variant differs
  if stat --version >/dev/null 2>&1; then
    ts="$(stat -c '%y' "$f" 2>/dev/null || stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "$f")"
  else
    ts="$(stat -f '%Sm' -t '%Y-%m-%d %H:%M:%S' "$f" 2>/dev/null || echo "")"
  fi
  echo "$f|$b|$ts"
}

pick_source() {
  # honor explicit choice
  case "$SOURCE" in
    usb|local) echo "$SOURCE"; return;;
  esac
  # auto: prefer USB if mounted and has backups
  if mountpoint -q /mnt/backup_usb && ls -1 "$USB_DIR"/backup_*.tar.gz >/dev/null 2>&1; then
    echo "usb"
  else
    echo "local"
  fi
}

# ---- Parse args --------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from)  shift; SOURCE="${1:-auto}";;
    --dry-run) DRY_RUN=true;;
    --preview) PREVIEW=true;;
    --port)  shift; PORT="${1:-9000}";;
    -h|--help)
      cat <<USAGE
Usage: $0 [--from auto|usb|local] [--dry-run] [--preview] [--port N]
  --from auto   : prefer USB if mounted & has backups; else local [default]
  --from usb    : use USB backups ($USB_DIR)
  --from local  : use local backups ($LOCAL_DIR)
  --dry-run     : extract into a test folder (no changes to live app)
  --preview     : after dry-run, run Flask on 0.0.0.0:\$PORT (default 9000)
  --port N      : port for --preview
USAGE
      exit 0;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1;;
  esac
  shift
done

# ---- Print summary of newest backups in both locations -----------------------
usb_info="$(latest_archive "$USB_DIR")"
loc_info="$(latest_archive "$LOCAL_DIR")"

if [[ -n "$usb_info" ]]; then
  IFS='|' read -r _usb_path _usb_base _usb_ts <<<"$usb_info"
  echo "[SUMMARY] USB latest : ${_usb_base:-N/A}  (${_usb_ts:-unknown})  at $USB_DIR"
else
  echo "[SUMMARY] USB latest : (none found) at $USB_DIR"
fi

if [[ -n "$loc_info" ]]; then
  IFS='|' read -r _loc_path _loc_base _loc_ts <<<"$loc_info"
  echo "[SUMMARY] Local latest: ${_loc_base:-N/A}  (${_loc_ts:-unknown})  at $LOCAL_DIR"
else
  echo "[SUMMARY] Local latest: (none found) at $LOCAL_DIR"
fi

# ---- Decide effective source & locate archive --------------------------------
SOURCE_EFF="$(pick_source)"
case "$SOURCE_EFF" in
  usb)   SRC_DIR="$USB_DIR" ;;
  local) SRC_DIR="$LOCAL_DIR" ;;
esac

echo "[INFO] Restore source: $SOURCE_EFF ($SRC_DIR)"
[[ -d "$SRC_DIR" ]] || { echo "[ERROR] Source dir not found: $SRC_DIR"; exit 1; }

ARCHIVE="$(ls -1t "$SRC_DIR"/backup_*.tar.gz 2>/dev/null | head -1 || true)"
[[ -n "${ARCHIVE:-}" ]] || { echo "[ERROR] No backup_*.tar.gz found in $SRC_DIR"; exit 1; }
SHA="${ARCHIVE}.sha256"

echo "[INFO] Latest archive: $(basename "$ARCHIVE")"

# ---- Verify checksum if available -------------------------------------------
if [[ -f "$SHA" ]]; then
  echo "[INFO] Verifying checksum with $(basename "$SHA") ..."
  sha256sum -c "$SHA"
else
  echo "[WARN] No checksum file found; skipping verification."
fi

TS="$(date +'%Y-%m-%d_%H-%M-%S')"

if $DRY_RUN; then
  # ---- DRY RUN: extract to a test folder, do not modify live app ------------
  TEST_DIR="$PROJECT/restore_test_$TS"
  echo "[INFO] DRY-RUN: creating test folder: $TEST_DIR"
  mkdir -p "$TEST_DIR"

  echo "[INFO] DRY-RUN: extracting archive into test folder..."
  tar -xzf "$ARCHIVE" -C "$TEST_DIR"

  echo "[INFO] DRY-RUN: first-level items in test folder:"
  (cd "$TEST_DIR" && ls -lah | sed -n '1,50p')

  if $PREVIEW; then
    echo
    echo "[INFO] PREVIEW: running Flask from test folder on 0.0.0.0:${PORT}"
    echo "[INFO] PREVIEW: Press Ctrl+C to stop the preview server."
    cd "$TEST_DIR"
    if [[ -f "venv/bin/activate" ]]; then
      # shellcheck disable=SC1091
      source venv/bin/activate
    fi
    FLASK_APP=app.py flask run --host=0.0.0.0 --port "$PORT"
  else
    echo
    echo "[INFO] DRY-RUN complete. Live app was NOT modified."
    echo "[INFO] Inspect files under: $TEST_DIR"
    echo "[INFO] Remove test folder later with: rm -rf \"$TEST_DIR\""
  fi
  exit 0
fi

# ---- REAL RESTORE: snapshot current, stop app, extract into live folder -----
PRE_SNAP="$LOCAL_DIR/restore_pre_${TS}.tar.gz"
echo "[INFO] Creating pre-restore snapshot: $(basename "$PRE_SNAP")"
tar -czf "$PRE_SNAP" --exclude="./backups" -C "$PROJECT" .

echo "[INFO] Stopping gunicorn..."
sudo systemctl stop gunicorn

echo "[INFO] Restoring files from archive into $PROJECT ..."
tar -xzf "$ARCHIVE" -C "$PROJECT"

echo "[INFO] Starting gunicorn..."
sudo systemctl start gunicorn
sleep 1
sudo systemctl status gunicorn --no-pager -l | sed -n '1,12p'

echo "[INFO] Restore complete."
echo "[INFO] Pre-restore snapshot saved at: $PRE_SNAP"
