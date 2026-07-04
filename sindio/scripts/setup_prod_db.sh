#!/usr/bin/env bash
# Sindio — Production Database Bootstrap
# =======================================
# Sets up PostgreSQL for production use.
# Supports Railway CLI, local Docker, or AWS RDS.
#
# Usage:
#   ./scripts/setup_prod_db.sh railway        # Provision Railway PostgreSQL
#   ./scripts/setup_prod_db.sh docker         # Local docker-compose DB
#   ./scripts/setup_prod_db.sh aws            # AWS RDS via Terraform

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODE="${1:-docker}"

echo "=========================================="
echo "Sindio Production DB Bootstrap"
echo "Mode: ${MODE}"
echo "=========================================="

case "${MODE}" in
  railway)
    echo "[ACTION] Provisioning Railway PostgreSQL..."
    if ! command -v railway &> /dev/null; then
      echo "[ERROR] Railway CLI not installed. Install: npm install -g @railway/cli"
      exit 1
    fi
    railway add --database postgres
    echo "[OK] Railway PostgreSQL provisioned."
    echo "[INFO] Set DATABASE_URL in Railway dashboard from the provisioned service."
    ;;

  docker)
    echo "[ACTION] Starting PostgreSQL via docker-compose..."
    cd "${PROJECT_DIR}/sindio/docker"
    docker compose -f docker-compose.yml up -d postgres
    echo "[OK] PostgreSQL container started on port 5432"
    echo "[INFO] Waiting for PostgreSQL to be ready..."
    sleep 5
    for i in {1..30}; do
      if docker compose exec -T postgres pg_isready -U sindio_user 2>/dev/null; then
        echo "[OK] PostgreSQL is accepting connections"
        break
      fi
      sleep 1
    done
    echo "[INFO] Running migrations..."
    docker compose exec -T postgres psql -U sindio_user -d sindio -f /docker-entrypoint-initdb.d/001_init.sql 2>/dev/null || true
    echo "[OK] Migrations applied"
    ;;

  aws)
    echo "[ACTION] Creating AWS RDS PostgreSQL via Terraform..."
    cd "${PROJECT_DIR}/sindio/terraform"
    if [ ! -f .terraform/terraform.tfstate ]; then
      echo "[ACTION] Running terraform init..."
      terraform init
    fi
    terraform plan -var-file=prod.tfvars -target=module.rds
    read -p "Type 'APPLY' to create RDS instance: " CONFIRM
    if [ "${CONFIRM}" == "APPLY" ]; then
      terraform apply -var-file=prod.tfvars -target=module.rds
      echo "[OK] RDS instance created"
    else
      echo "Aborted."
      exit 1
    fi
    ;;

  *)
    echo "Usage: $0 {railway|docker|aws}"
    exit 1
    ;;
esac

echo "=========================================="
echo "Database bootstrap complete."
echo "Next steps:"
echo "  1. Set DB_HOST / DATABASE_URL in your .env"
echo "  2. Run: ./scripts/seed_test_data.py"
echo "  3. Run: cd backend/core && poetry run python -m app.ingestion"
echo "=========================================="
