#!/bin/bash

# Aurora RAG - Automated Backup Script
# Usage: ./backup.sh
# Add to crontab: 0 2 * * * /opt/aurora/scripts/backup.sh >> /var/log/aurora-backup.log 2>&1

set -e

# Configuration
BACKUP_ROOT="/opt/aurora/backups"
DATA_DIR="/opt/aurora/data"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="aurora_backup_${TIMESTAMP}.tar.gz"

# Create backup directory
mkdir -p "$BACKUP_ROOT"

echo "[$(date)] Starting backup: $BACKUP_NAME"

# Create tarball of data directory (includes SQLite DB and ChromaDB)
# Using --ignore-failed-read to avoid stopping if a file changes during read (e.g. WAL files)
tar -czf "${BACKUP_ROOT}/${BACKUP_NAME}" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")" --warning=no-file-changed

echo "[$(date)] Backup created successfully: ${BACKUP_ROOT}/${BACKUP_NAME}"
echo "[$(date)] Size: $(du -h "${BACKUP_ROOT}/${BACKUP_NAME}" | cut -f1)"

# Cleanup old backups
echo "[$(date)] Cleaning up backups older than $RETENTION_DAYS days..."
find "$BACKUP_ROOT" -name "aurora_backup_*.tar.gz" -mtime +$RETENTION_DAYS -delete

echo "[$(date)] Backup process complete."
