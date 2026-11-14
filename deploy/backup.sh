#!/bin/bash
# Daily SQLite backup: /opt/health-agent/backend/data/health.db
set -euo pipefail
SRC="/opt/health-agent/backend/data/health.db"
DEST="/var/backups/health-agent"
KEEP=14
mkdir -p "$DEST"
STAMP=$(date +%Y%m%d-%H%M%S)
sqlite3 "$SRC" ".backup '$DEST/health-$STAMP.db'"
gzip -f "$DEST/health-$STAMP.db"
if [ -d /opt/health-agent/backend/data/users ]; then
  tar czf "$DEST/users-$STAMP.tar.gz" -C /opt/health-agent/backend/data users
fi
find "$DEST" -name 'health-*.db.gz' -mtime +$KEEP -delete
find "$DEST" -name 'users-*.tar.gz' -mtime +$KEEP -delete
echo "backup ok: $DEST/health-$STAMP.db.gz"
