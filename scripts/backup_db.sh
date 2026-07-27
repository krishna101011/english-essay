#!/usr/bin/env bash
# Backs up app.db to a gzip-compressed, timestamped snapshot and keeps only
# the last 7 rotations. Meant to be run on a schedule (e.g. a daily cron job)
# on whatever machine actually hosts app.db.
#
# Usage: scripts/backup_db.sh
#
# To point this at off-server storage later (once real infra exists), add a
# step after the gzip below that copies the newest backup out, e.g.:
#   aws s3 cp "$BACKUP_FILE" s3://your-bucket/backups/
#   rclone copy "$BACKUP_FILE" remote:backups/
#   rsync "$BACKUP_FILE" user@offsite-host:/path/to/backups/
# Nothing like that is wired up here - this script only writes local,
# rotated snapshots into the gitignored backups/ folder.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/app.db}"
BACKUP_DIR="$PROJECT_ROOT/backups"
KEEP=7

if [ ! -f "$DB_PATH" ]; then
    echo "No database found at $DB_PATH - nothing to back up." >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
SNAPSHOT_PATH="$BACKUP_DIR/app-$TIMESTAMP.db"
BACKUP_FILE="$SNAPSHOT_PATH.gz"

# sqlite3's ".backup" takes a consistent snapshot even while the app is
# writing to app.db (WAL mode lets readers and writers run concurrently),
# unlike a plain file copy which could grab a half-written page.
sqlite3 "$DB_PATH" ".backup '$SNAPSHOT_PATH'"
gzip -f "$SNAPSHOT_PATH"

echo "Backed up $DB_PATH -> $BACKUP_FILE"

# Rotation: keep only the $KEEP most recent snapshots.
mapfile -t existing < <(ls -1t "$BACKUP_DIR"/app-*.db.gz 2>/dev/null)
if [ "${#existing[@]}" -gt "$KEEP" ]; then
    for old in "${existing[@]:$KEEP}"; do
        echo "Removing old backup: $old"
        rm -f "$old"
    done
fi
