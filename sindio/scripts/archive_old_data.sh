#!/usr/bin/env bash
# Sindio — Data Cleanup / Archival Script
# Moves old data to S3 and deletes from PostgreSQL.
#
# Usage:
#   ./scripts/archive_old_data.sh [s3-bucket-name]

set -euo pipefail

S3_BUCKET="${1:-}"
ARCHIVE_DATE=$(date -d '90 days ago' +%Y-%m-%d)
ARCHIVE_FILE="/tmp/sindio_archive_${ARCHIVE_DATE}.csv.gz"

DB_URL="${DATABASE_URL:-postgresql://${DB_USER:-sindio_user}:${DB_PASSWORD:-}@${DB_HOST:-localhost}:${DB_PORT:-5432}/${DB_NAME:-sindio}}"

echo "=========================================="
echo "Sindio Data Archival"
echo "Archive date: ${ARCHIVE_DATE}"
echo "=========================================="

# Export old sensor readings to CSV
psql "${DB_URL}" -c "
COPY (
    SELECT * FROM sensor_readings WHERE timestamp < '${ARCHIVE_DATE}'
) TO STDOUT WITH CSV HEADER;
" | gzip > "${ARCHIVE_FILE}"

echo "[OK] Exported ${ARCHIVE_FILE} ($(du -h ${ARCHIVE_FILE} | cut -f1))"

# Upload to S3 if bucket provided
if [ -n "${S3_BUCKET}" ]; then
    aws s3 cp "${ARCHIVE_FILE}" "s3://${S3_BUCKET}/archives/sensor_readings_${ARCHIVE_DATE}.csv.gz" --storage-class GLACIER
    echo "[OK] Uploaded to S3"
fi

# Delete archived rows
psql "${DB_URL}" -c "DELETE FROM sensor_readings WHERE timestamp < '${ARCHIVE_DATE}';"
echo "[OK] Deleted old sensor readings"

# Vacuum to reclaim space
psql "${DB_URL}" -c "VACUUM sensor_readings;"
echo "[OK] Vacuum complete"

echo "=========================================="
echo "Archival complete."
echo "=========================================="
