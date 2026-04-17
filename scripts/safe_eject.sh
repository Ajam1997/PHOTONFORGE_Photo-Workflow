#!/bin/bash
# FR-1.10: Flush Darktable SQLite WAL and safely unmount a volume.
# Usage: safe_eject.sh <mount_point> [darktable_db_path]
set -euo pipefail

MOUNT_POINT="${1:?Usage: safe_eject.sh <mount_point> [darktable_db_path]}"
DARKTABLE_DB="${2:-}"

log() { printf '[safe_eject] %s\n' "$*" >&2; }

# 1. Flush Darktable SQLite WAL if DB path provided
if [ -n "$DARKTABLE_DB" ] && [ -f "$DARKTABLE_DB" ]; then
    log "Flushing SQLite WAL: $DARKTABLE_DB"
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$DARKTABLE_DB" "PRAGMA wal_checkpoint(TRUNCATE);" || \
            log "WARNING: WAL flush failed — proceeding with eject anyway"
    else
        python3 -c "
import sqlite3, sys
try:
    conn = sqlite3.connect(sys.argv[1])
    conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    conn.close()
except Exception as e:
    print(f'WARNING: WAL flush failed: {e}', file=sys.stderr)
" "$DARKTABLE_DB" || true
    fi
fi

# 2. Sync filesystem buffers
log "Syncing filesystem buffers..."
sync

# 3. Unmount
log "Unmounting $MOUNT_POINT"
if command -v udisksctl >/dev/null 2>&1; then
    udisksctl unmount --block-device "$(findmnt -n -o SOURCE "$MOUNT_POINT")" --no-user-interaction
else
    umount "$MOUNT_POINT"
fi

log "Safe eject complete: $MOUNT_POINT"
