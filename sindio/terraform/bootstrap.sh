#!/usr/bin/env bash
# Terraform S3 Backend Bootstrap Script
# Creates the S3 bucket + DynamoDB table for remote state locking.
#
# Usage:
#   cd terraform && ./bootstrap.sh [aws-profile-name]
#   (requires AWS CLI + terraform CLI installed)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AWS_PROFILE="${1:-default}"
BUCKET_NAME="sindio-tfstate"
TABLE_NAME="sindio-tfstate-lock"
REGION="us-east-1"

export AWS_PROFILE

echo "=========================================="
echo "Sindio Terraform Backend Bootstrap"
echo "AWS Profile: ${AWS_PROFILE}"
echo "Region: ${REGION}"
echo "=========================================="

# ── Create S3 bucket ───────────────────────────────────────────
if aws s3api head-bucket --bucket "${BUCKET_NAME}" 2>/dev/null; then
    echo "[OK] S3 bucket ${BUCKET_NAME} already exists"
else
    echo "[ACTION] Creating S3 bucket ${BUCKET_NAME}..."
    aws s3api create-bucket \
        --bucket "${BUCKET_NAME}" \
        --region "${REGION}" \
        2>/dev/null || {
            echo "[ERROR] Failed to create bucket. Do you have AWS CLI permissions?"
            exit 1
        }
    echo "[OK] Bucket created"
fi

# ── Enable versioning ──────────────────────────────────────────
echo "[ACTION] Enabling bucket versioning..."
aws s3api put-bucket-versioning \
    --bucket "${BUCKET_NAME}" \
    --versioning-configuration Status=Enabled

# ── Enable encryption ──────────────────────────────────────────
echo "[ACTION] Enabling server-side encryption..."
aws s3api put-bucket-encryption \
    --bucket "${BUCKET_NAME}" \
    --server-side-encryption-configuration '{
        "Rules": [{
            "ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"},
            "BucketKeyEnabled": true
        }]
    }'

# ── Block public access ──────────────────────────────────────
echo "[ACTION] Blocking public access..."
aws s3api put-public-access-block \
    --bucket "${BUCKET_NAME}" \
    --public-access-block-configuration '{
        "BlockPublicAcls": true,
        "IgnorePublicAcls": true,
        "BlockPublicPolicy": true,
        "RestrictPublicBuckets": true
    }'

# ── Create DynamoDB lock table ─────────────────────────────────
if aws dynamodb describe-table --table-name "${TABLE_NAME}" >/dev/null 2>&1; then
    echo "[OK] DynamoDB table ${TABLE_NAME} already exists"
else
    echo "[ACTION] Creating DynamoDB lock table ${TABLE_NAME}..."
    aws dynamodb create-table \
        --table-name "${TABLE_NAME}" \
        --attribute-definitions AttributeName=LockID,AttributeType=S \
        --key-schema AttributeName=LockID,KeyType=HASH \
        --billing-mode PAY_PER_REQUEST \
        --region "${REGION}"
    echo "[OK] DynamoDB table created"
fi

echo ""
echo "=========================================="
echo "Bootstrap complete!"
echo "S3 bucket: ${BUCKET_NAME}"
echo "DynamoDB table: ${TABLE_NAME}"
echo "=========================================="
echo ""
echo "You can now run:"
echo "  cd ${SCRIPT_DIR}"
echo "  terraform init"
echo "  terraform plan -var-file=dev.tfvars"
echo "  terraform apply -var-file=dev.tfvars"
