#!/usr/bin/env bash
# Sindio — PostgreSQL Backup Script
# Creates timestamped pg_dump archives to /tmp/sindio_backups/
# and optionally uploads to S3.
#
# Usage:
#   ./scripts/backup_db.sh [s3-bucket-name]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKUP_DIR="/tmp/sindio_backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_NAME="${DB_NAME:-sindio}"
DB_USER="${DB_USER:-sindio_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_PASSWORD="${DB_PASSWORD:-}"
S3_BUCKET="${1:-}"

export PGPASSWORD="${DB_PASSWORD}"

mkdir -p "${BACKUP_DIR}"

echo "=========================================="
echo "Sindio PostgreSQL Backup"
echo "Database: ${DB_NAME}@${DB_HOST}:${DB_PORT}"
echo "Backup:   ${BACKUP_DIR}/sindio_${TIMESTAMP}.sql.gz"
echo "=========================================="

# ── Dump ─────────────────────────────────────────────────────────
pg_dump \
    -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" \
    -d "${DB_NAME}" \
    --verbose \
    --no-owner \
    --no-privileges \
    --clean \
    --if-exists \
    --exclude-table='pg_stat*' \
    --exclude-table='pg_catalog*' \
    | gzip > "${BACKUP_DIR}/sindio_${TIMESTAMP}.sql.gz"

if [ $? -eq 0 ]; then
    echo "[OK] Backup created: ${BACKUP_DIR}/sindio_${TIMESTAMP}.sql.gz"
    ls -lh "${BACKUP_DIR}/sindio_${TIMESTAMP}.sql.gz"
else
    echo "[ERROR] pg_dump failed"
    exit 1
fi

# ── Upload to S3 (if bucket provided) ────────────────────────
if [ -n "${S3_BUCKET}" ]; then
    echo "[ACTION] Uploading to s3://${S3_BUCKET}/backups/sindio_${TIMESTAMP}.sql.gz ..."
    aws s3 cp "${BACKUP_DIR}/sindio_${TIMESTAMP}.sql.gz" \
        "s3://${S3_BUCKET}/backups/sindio_${TIMESTAMP}.sql.gz" \
        --storage-class STANDARD_IA
    echo "[OK] Uploaded to S3"
fi

# ── Cleanup old backups ────────────────────────────────────────
echo "[ACTION] Cleaning up backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "sindio_*.sql.gz" -mtime +${RETENTION_DAYS} -delete

echo "=========================================="
echo "Backup complete."
echo "=========================================="
