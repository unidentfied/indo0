#!/usr/bin/env bash
# Sindio — Kubernetes Cluster Deployment
# ========================================
# Automates EKS cluster creation and Sindio deployment.
#
# Prerequisites:
#   - AWS CLI configured
#   - kubectl installed
#   - Terraform initialized (bootstrap.sh run)
#   - Docker images pushed to GHCR
#
# Usage:
#   ./scripts/deploy_k8s.sh [dev|prod]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV="${1:-dev}"

echo "=========================================="
echo "Sindio K8s Deployment"
echo "Environment: ${ENV}"
echo "=========================================="

# ── Terraform: Create infrastructure ─────────────────────────
echo "[ACTION] Running Terraform..."
cd "${PROJECT_DIR}/sindio/terraform"
terraform plan -var-file="${ENV}.tfvars"
read -p "Type 'APPLY' to create infrastructure: " TF_CONFIRM
if [ "${TF_CONFIRM}" != "APPLY" ]; then
    echo "Aborted."
    exit 1
fi
terraform apply -var-file="${ENV}.tfvars"

# ── Configure kubectl ─────────────────────────────────────
echo "[ACTION] Configuring kubectl..."
aws eks update-kubeconfig --region us-east-1 --name "sindio-${ENV}"

# ── Verify cluster access ─────────────────────────────────
echo "[ACTION] Verifying cluster..."
kubectl get nodes

# ── Apply K8s manifests ───────────────────────────────────
echo "[ACTION] Applying K8s manifests..."
cd "${PROJECT_DIR}/sindio/k8s"
kubectl apply -f 00-namespace.yaml
kubectl apply -f 01-configmap.yaml
kubectl apply -f 02-secrets.yaml
kubectl apply -f 03-pvc.yaml
kubectl apply -f 04-deployments.yaml
kubectl apply -f 05-services.yaml
kubectl apply -f 06-hpa.yaml

# ── Wait for rollout ──────────────────────────────────────
echo "[ACTION] Waiting for deployments..."
kubectl rollout status deployment/sindio-api -n sindio --timeout=300s
kubectl rollout status deployment/sindio-frontend -n sindio --timeout=300s

# ── Verify health ─────────────────────────────────────────
echo "[ACTION] Health checks..."
API_URL=$(kubectl get svc sindio-api -n sindio -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || echo "pending")
echo "API endpoint: ${API_URL}"

# ── Apply monitoring ──────────────────────────────────────
echo "[ACTION] Applying monitoring stack..."
kubectl apply -f 07-istio-virtualservice.yaml 2>/dev/null || echo "Istio not installed, skipping"
kubectl apply -f 08-servicemonitors.yaml 2>/dev/null || echo "Prometheus Operator not installed, skipping"

echo "=========================================="
echo "Deployment complete!"
echo "=========================================="
echo "Commands:"
echo "  kubectl get pods -n sindio"
echo "  kubectl logs -n sindio deployment/sindio-api"
echo "  kubectl get svc -n sindio"
