#!/bin/bash

# Set variables
VOLUME_NAME="negotiation-plugin_mongodb-data"
BACKUP_DIR="./backup_data"
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="${BACKUP_DIR}/${VOLUME_NAME}_backup_${TIMESTAMP}.tar.gz"

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Use a temporary container to access the volume and create a backup
docker run --rm \
  -v "${VOLUME_NAME}":/data \
  -v "${BACKUP_DIR}":/backup \
  alpine \
  tar czf /backup/$(basename "$BACKUP_FILE") -C /data .

echo "Backup completed: $BACKUP_FILE"

# Delete old backups older than 7 days
find "$BACKUP_DIR" -type f -name "${VOLUME_NAME}_backup_*.tar.gz" -mtime +7 -exec rm {} \;

echo "Old backups older than 7 days deleted from $BACKUP_DIR"