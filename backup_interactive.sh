#!/usr/bin/env bash
set -Eeuo pipefail

# Paths
BACKUP_SRC="/home/roland/e_learning_portal"
BACKUP_DEST_LOCAL="$BACKUP_SRC/backups"
BACKUP_DEST_USB="/mnt/backup_usb/e_learning_portal"

# Names
DATE="$(date +'%Y-%m-%d_%H-%M-%S')"
ARCHIVE_NAME="backup_${DATE}.tar.gz"
TMP_ARCHIVE="/tmp/${ARCHIVE_NAME}"
FINAL_ARCHIVE="${BACKUP_DEST_LOCAL}/${ARCHIVE_NAME}"
FINAL_SHA="${FINAL_ARCHIVE}.sha256"

mkdir -p "$BACKUP_DEST_LOCAL"

echo "[INFO] Creating backup archive: ${ARCHIVE_NAME}"
# Create archive OUTSIDE tree, exclude backups dir
tar -czf "$TMP_ARCHIVE" --exclude="./backups" -C "$BACKUP_SRC" .
mv "$TMP_ARCHIVE" "$FINAL_ARCHIVE"
echo "[INFO] Backup archive created at $FINAL_ARCHIVE"

# Checksums
echo "[INFO] Writing checksum: $FINAL_SHA"
sha256sum "$FINAL_ARCHIVE" | tee "$FINAL_SHA" >/dev/null
echo "[INFO] Verifying checksum..."
sha256sum -c "$FINAL_SHA"

# Prune local (keep last 7)
echo "[INFO] Cleaning up old local backups (keeping last 7)..."
ls -1t "$BACKUP_DEST_LOCAL"/backup_*.tar.gz       2>/dev/null | tail -n +8 | xargs -r rm --
ls -1t "$BACKUP_DEST_LOCAL"/backup_*.tar.gz.sha256 2>/dev/null | tail -n +8 | xargs -r rm --
echo "[INFO] Local backup cleanup done."

# USB copy (if mounted)
if mountpoint -q /mnt/backup_usb; then
  echo "[INFO] USB drive is mounted. Copying backup + checksum to $BACKUP_DEST_USB ..."
  mkdir -p "$BACKUP_DEST_USB"
  cp "$FINAL_ARCHIVE" "$BACKUP_DEST_USB/" 
  cp "$FINAL_SHA"     "$BACKUP_DEST_USB/" 2>/dev/null || true
  echo "[INFO] USB backup complete."
else
  echo "[WARNING] USB drive not mounted. Skipping off-device backup copy (archive + checksum)."
fi

echo "[INFO] Backup process completed successfully!"
