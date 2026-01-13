#!/bin/bash
# Backup Prometheus data to ensure no data loss

BACKUP_DIR="./backups/prometheus"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

echo "📦 Creating Prometheus backup..."

# Create backup directory
mkdir -p "$BACKUP_DIR"

# Backup using docker cp
docker cp aurora-prometheus:/prometheus "$BACKUP_DIR/prometheus_$TIMESTAMP"

echo "✅ Backup created: $BACKUP_DIR/prometheus_$TIMESTAMP"
echo ""
echo "To restore:"
echo "  docker cp $BACKUP_DIR/prometheus_$TIMESTAMP/. aurora-prometheus:/prometheus"
echo "  docker restart aurora-prometheus"
