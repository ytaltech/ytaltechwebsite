#!/usr/bin/env bash
# ==============================================================================
# Ytal Tech Solutions & Services LLP - Automated PostgreSQL Database Backup
# ==============================================================================
# Cron setup: Run daily at 02:00 AM server time
# Crontab line: 0 2 * * * /opt/ytaltech/deployment/backup_db.sh >> /var/log/ytaltech_backup.log 2>&1
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="${PROJECT_ROOT}/.env"

# 1. Load environment configuration
if [ -f "$ENV_FILE" ]; then
    # Export non-comment lines
    set -a
    # shellcheck disable=SC1090
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^\s*$')
    set +a
else
    echo "[ERROR] Environment file $ENV_FILE not found." >&2
    exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "[ERROR] DATABASE_URL is not defined in $ENV_FILE." >&2
    exit 1
fi

# 2. Setup backup directories
BACKUP_DIR="${PROJECT_ROOT}/backups"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

TIMESTAMP="$(date +'%Y%m%d_%H%M%S')"
BACKUP_FILE="${BACKUP_DIR}/ytaltech_db_${TIMESTAMP}.dump"
GZ_FILE="${BACKUP_FILE}.gz"

echo "=========================================================="
echo "Starting PostgreSQL Backup: $(date)"
echo "Target: $GZ_FILE"
echo "=========================================================="

# 3. Execute pg_dump using DATABASE_URL directly
# Works with both postgresql:// and postgres:// formats
CLEAN_DB_URL="${DATABASE_URL/postgresql+psycopg2:\/\//postgresql:\/\/}"

pg_dump "$CLEAN_DB_URL" --format=custom --compress=9 --file="$BACKUP_FILE"

# Gzip archive for double security and integrity check
gzip -c "$BACKUP_FILE" > "$GZ_FILE"
rm -f "$BACKUP_FILE"
chmod 600 "$GZ_FILE"

FILE_SIZE="$(du -h "$GZ_FILE" | cut -f1)"
echo "[SUCCESS] Backup completed successfully. Archive size: $FILE_SIZE"

# 4. Enforce Retention Policy: Automatically delete backups older than 14 days
echo "Applying retention policy: Purging backups older than 14 days..."
find "$BACKUP_DIR" -type f -name "ytaltech_db_*.dump.gz" -mtime +14 -exec rm -f {} \;

# 5. Offsite sync recommendation (Optional: configure S3 / Cloud Storage / SFTP)
# If AWS CLI is configured, sync to private S3 bucket offsite:
# if command -v aws &> /dev/null && [ -n "${BACKUP_S3_BUCKET:-}" ]; then
#     echo "Syncing backup offsite to s3://${BACKUP_S3_BUCKET}/..."
#     aws s3 cp "$GZ_FILE" "s3://${BACKUP_S3_BUCKET}/db_backups/$(basename "$GZ_FILE")"
# fi

echo "Backup finished: $(date)"
echo "=========================================================="
