#!/usr/bin/env bash
# Sindio — Kubernetes Cluster Deployment
# ========================================
# Automates EKS cluster creation and Sindio deployment via Kustomize.
#
# Prerequisites:
#   - AWS CLI configured
#   - kubectl installed
#   - kustomize installed (or use 'kubectl apply -k')
#   - Docker images pushed to registry
#
# Usage:
#   ./scripts/deploy_k8s.sh [dev|staging|prod]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV="${1:-dev}"

OVERLAY_DIR="${PROJECT_DIR}/k8s/overlays/${ENV}"

if [ ! -d "${OVERLAY_DIR}" ]; then
    echo "ERROR: Kustomize overlay '${ENV}' not found at ${OVERLAY_DIR}"
    echo "Valid environments: dev, staging, prod"
    exit 1
fi

echo "=========================================="
echo "Sindio K8s Deployment"
echo "Environment: ${ENV}"
echo "Overlay: ${OVERLAY_DIR}"
echo "=========================================="

# ── Terraform: Create infrastructure (optional) ─────────────
TERRAFORM_DIR="${PROJECT_DIR}/../terraform"
if [ -d "${TERRAFORM_DIR}" ]; then
    echo "[ACTION] Running Terraform..."
    cd "${TERRAFORM_DIR}"
    terraform plan -var-file="${ENV}.tfvars"
    read -p "Type 'APPLY' to create infrastructure: " TF_CONFIRM
    if [ "${TF_CONFIRM}" != "APPLY" ]; then
        echo "Aborted."
        exit 1
    fi
    terraform apply -var-file="${ENV}.tfvars"
else
    echo "[SKIP] Terraform directory not found — assuming infrastructure exists."
fi

# ── Configure kubectl ─────────────────────────────────────
echo "[ACTION] Configuring kubectl..."
aws eks update-kubeconfig --region us-east-1 --name "sindio-${ENV}"

# ── Verify cluster access ─────────────────────────────────
echo "[ACTION] Verifying cluster..."
kubectl get nodes

# ── Apply K8s manifests via Kustomize ─────────────────────
echo "[ACTION] Applying K8s manifests via Kustomize..."
cd "${OVERLAY_DIR}"
kubectl apply -k .

# ── Run database migrations ───────────────────────────────
echo "[ACTION] Running database migrations..."
cd "${PROJECT_DIR}"
# Infer target namespace from current kubectl context
K8S_NS=$(kubectl config view --minify --output 'jsonpath={..namespace}')
K8S_NS="${K8S_NS:-sindio}"

# Generate the migrations ConfigMap from SQL files
kubectl create configmap sindio-migrations \
    --from-file=backend/migrations/ \
    --namespace "${K8S_NS}" \
    --dry-run=client -o yaml | kubectl apply -f -

# Run the migration job
kubectl apply -f k8s/migration-job.yaml --namespace "${K8S_NS}"
kubectl wait --for=condition=complete job/sindio-migrate --namespace "${K8S_NS}" --timeout=300s || {
    echo "ERROR: Migrations failed. Check logs with:"
    echo "  kubectl logs job/sindio-migrate --namespace ${K8S_NS}"
    exit 1
}

# ── Wait for rollout ──────────────────────────────────────
echo "[ACTION] Waiting for deployments..."
kubectl rollout status deployment/sindio-api --timeout=300s
kubectl rollout status deployment/sindio-frontend --timeout=300s

# ── Verify health ─────────────────────────────────────────
echo "[ACTION] Health checks..."
API_URL=$(kubectl get svc sindio-api -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
echo "API endpoint: ${API_URL}"

echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Commands:"
echo "  kubectl get pods"
echo "  kubectl logs deployment/sindio-api"
echo "  kubectl get svc"
