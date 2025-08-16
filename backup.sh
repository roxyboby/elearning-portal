#!/usr/bin/env bash
set -Eeuo pipefail

log(){ echo "[$(date +'%F %T')] $*"; }

# Where this script lives = project root
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

TS="$(date +'%Y-%m-%d_%H-%M-%S')"
NOTE="${1:-}"                          # optional note: ./backup.sh "pre-ui-pass"
NOTE_TAG="${NOTE//[^a-zA-Z0-9_-]/_}"   # sanitize
SUFFIX="${NOTE_TAG:+_"$NOTE_TAG"}"

BACKUP_DIR="$PROJECT_DIR/backups"
mkdir -p "$BACKUP_DIR"

log "Starting backup$([ -n "$NOTE_TAG" ] && echo " ($NOTE_TAG)")"

# Build include list (only if paths exist)
INCLUDE=( app.py models.py templates static content instance .env requirements.txt )
FILES=()
for p in "${INCLUDE[@]}"; do
  [[ -e "$p" ]] && FILES+=("$p")
done

if ((${#FILES[@]}==0)); then
  log "Nothing to archive (no expected project files found)."
  exit 1
fi

ARCHIVE="$BACKUP_DIR/elp_backup_${TS}${SUFFIX}.tgz"

log "Creating source archive: $(basename "$ARCHIVE")"
tar \
  --exclude='venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -czf "$ARCHIVE" "${FILES[@]}"

# SQLite backup (safe online backup if sqlite3 is available)
DB_SRC="instance/portal.db"
if [[ -f "$DB_SRC" ]]; then
  DB_OUT="$BACKUP_DIR/portal_${TS}${SUFFIX}.db"
  if command -v sqlite3 >/dev/null 2>&1; then
    log "Backing up SQLite DB via sqlite3 .backup → $(basename "$DB_OUT")"
    sqlite3 "$DB_SRC" ".backup '$DB_OUT'"
  else
    log "sqlite3 not found; falling back to file copy → $(basename "$DB_OUT")"
    cp "$DB_SRC" "$DB_OUT"
  fi
else
  log "No SQLite DB found at $DB_SRC (skipping DB backup)"
fi

# Optional retention: keep last 10 backups (uncomment to enable)
# log "Pruning old backups (keep last 10)..."
# ls -1t "$BACKUP_DIR"/elp_backup_*.tgz 2>/dev/null | tail -n +11 | xargs -r rm -f
# ls -1t "$BACKUP_DIR"/portal_*.db      2>/dev/null | tail -n +11 | xargs -r rm -f

log "Backup complete."
log "Archive: $ARCHIVE"
[[ -f "$DB_SRC" ]] && log "DB copy: $(ls -1t "$BACKUP_DIR"/portal_${TS}${SUFFIX}.db 2>/dev/null | head -n1)"

# Quick summary
echo "----"
ls -lh "$ARCHIVE" 2>/dev/null || true
[[ -f "$DB_SRC" ]] && ls -lh "$BACKUP_DIR"/portal_${TS}${SUFFIX}.db 2>/dev/null || true

# Restore tips (echo only)
cat <<'HELP'

Restore tips:
  # from project root
  tar -xzf backups/elp_backup_<timestamp>.tgz -C .
  cp backups/portal_<timestamp>.db instance/portal.db

Run with an optional note:
  ./backup.sh "pre-ui-pass"
HELP
