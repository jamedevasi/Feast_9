#!/bin/sh
# Simple backup of the SQLite database + exports.
# Usage (Docker): ./backup.sh
# Copies /data (inside the container volume) to a timestamped tar.gz on the host.
set -e
TS=$(date +%Y%m%d_%H%M%S)
OUT="feast9_backup_${TS}.tar.gz"
docker run --rm \
  -v feast9_data:/data:ro \
  -v "$(pwd)":/backup \
  alpine \
  sh -c "cd / && tar -czf /backup/${OUT} data"
echo "Backup written to ${OUT}"
