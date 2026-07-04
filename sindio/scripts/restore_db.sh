#!/usr/bin/env bash
# Sindio — PostgreSQL Restore Script
# Restores a pg_dump archive to the target database.
#
# Usage:
#   ./scripts/restore_db.sh <backup-file.sql.gz> [target-db-name]
#
# WARNING: This will DROP and RECREATE the target database.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <backup-file.sql.gz> [target-db-name]"
    echo ""
    echo "Examples:"
    echo "  $0 /tmp/sindio_backups/sindio_20240115_120000.sql.gz"
    echo "  $0 s3://sindio-prod-backups/backups/sindio_20240115_120000.sql.gz sindio_recovery"
    exit 1
fi

BACKUP_FILE="$1"
DB_NAME="${2:-sindio}"
DB_USER="${DB_USER:-sindio_user}"
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_PASSWORD="${DB_PASSWORD:-}"

export PGPASSWORD="${DB_PASSWORD}"

echo "=========================================="
echo "Sindio PostgreSQL Restore"
echo "WARNING: This will DESTROY and recreate ${DB_NAME}"
echo "Source: ${BACKUP_FILE}"
echo "=========================================="

# ── Confirm ────────────────────────────────────────────────────
read -p "Type 'RESTORE' to confirm: " CONFIRM
if [ "${CONFIRM}" != "RESTORE" ]; then
    echo "Aborted."
    exit 1
fi

# ── Download from S3 if needed ─────────────────────────────────
LOCAL_FILE="${BACKUP_FILE}"
if [[ "${BACKUP_FILE}" == s3://* ]]; then
    LOCAL_FILE="/tmp/sindio_restore_$(date +%s).sql.gz"
    echo "[ACTION] Downloading from S3..."
    aws s3 cp "${BACKUP_FILE}" "${LOCAL_FILE}"
    echo "[OK] Downloaded to ${LOCAL_FILE}"
fi

# ── Terminate existing connections ───────────────────────────────
echo "[ACTION] Terminating existing connections to ${DB_NAME}..."
psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d postgres -c "
    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
    WHERE datname = '${DB_NAME}' AND pid <> pg_backend_pid();
" || true

# ── Drop and recreate ──────────────────────────────────────────
echo "[ACTION] Dropping database ${DB_NAME}..."
dropdb -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" --if-exists "${DB_NAME}"

echo "[ACTION] Creating database ${DB_NAME}..."
createdb -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" "${DB_NAME}"

# ── Restore ────────────────────────────────────────────────────
echo "[ACTION] Restoring from ${LOCAL_FILE}..."
gunzip -c "${LOCAL_FILE}" | psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}"

# ── Verify ─────────────────────────────────────────────────────
TABLE_COUNT=$(psql -h "${DB_HOST}" -p "${DB_PORT}" -U "${DB_USER}" -d "${DB_NAME}" -t -c "
    SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';
" | xargs)
echo "[OK] Restore complete. ${TABLE_COUNT} public tables restored."

# ── Cleanup ──────────────────────────────────────────────────────
if [[ "${BACKUP_FILE}" == s3://* ]] && [ -f "${LOCAL_FILE}" ]; then
    rm -f "${LOCAL_FILE}"
fi

echo "=========================================="
echo "Restore complete."
echo "Database: ${DB_NAME} is now operational."
echo "=========================================="
