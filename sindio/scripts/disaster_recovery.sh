#!/usr/bin/env bash
# Sindio — Disaster Recovery Playbook
# =====================================
# Documented recovery procedures for all major failure scenarios.
# Read this BEFORE a disaster, execute during a disaster.
#
# Last updated: 2024-01

# ── 1. PostgreSQL Data Loss ────────────────────────────────────
# Symptoms: DB corruption, accidental DROP, ransomware
# Recovery time target (RTO): 30 min
# Recovery point objective (RPO): last nightly backup (max 24h)

## Step 1: Identify the last known-good backup
# Backups are in /tmp/sindio_backups/ (local) and s3://<bucket>/backups/ (remote)
# List local:
#   ls -lt /tmp/sindio_backups/sindio_*.sql.gz | head -5
# List S3:
#   aws s3 ls s3://sindio-prod-backups/backups/ | tail -10

## Step 2: Stop all services that write to DB
#   docker compose -f docker/docker-compose.yml stop core celery_worker celery_beat
# Or in K8s:
#   kubectl scale deployment sindio-core --replicas=0 -n sindio
#   kubectl scale deployment sindio-celery-worker --replicas=0 -n sindio
#   kubectl scale deployment sindio-celery-beat --replicas=0 -n sindio

## Step 3: Restore from backup
# Local backup:
#   ./scripts/restore_db.sh /tmp/sindio_backups/sindio_YYYYMMDD_HHMMSS.sql.gz
# S3 backup:
#   ./scripts/restore_db.sh s3://sindio-prod-backups/backups/sindio_YYYYMMDD_HHMMSS.sql.gz

## Step 4: Verify table counts
#   psql -h $DB_HOST -U $DB_USER -d sindio -c "SELECT COUNT(*) FROM infrastructure_nodes;"
#   psql -h $DB_HOST -U $DB_USER -d sindio -c "SELECT COUNT(*) FROM sensor_telemetry;"
#   psql -h $DB_HOST -U $DB_USER -d sindio -c "SELECT COUNT(*) FROM alerts;"

## Step 5: Resume services
#   docker compose -f docker/docker-compose.yml up -d core celery_worker celery_beat
# Or in K8s:
#   kubectl scale deployment sindio-core --replicas=1 -n sindio
#   kubectl scale deployment sindio-celery-worker --replicas=2 -n sindio

## Step 6: Health check
#   curl -f https://<railway-url>/health/ready
# Should return: {"status": "ready", "dependencies": {"postgres": "ok"}}

# ── 2. Redis / Celery Failure ──────────────────────────────────
# Symptoms: Tasks not processing, API errors on /simulate endpoints
# RTO: 5 min

## Step 1: Check Redis connectivity
#   redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD ping

## Step 2: If Redis is corrupted, flush and restart
#   redis-cli -h $REDIS_HOST -p $REDIS_PORT -a $REDIS_PASSWORD FLUSHALL
# This clears pending tasks (will be lost) but restores broker health.

## Step 3: Restart Celery workers
#   docker compose restart celery_worker celery_beat
# Or in K8s:
#   kubectl rollout restart deployment/sindio-celery-worker -n sindio
#   kubectl rollout restart deployment/sindio-celery-beat -n sindio

# ── 3. ML Core Failure ───────────────────────────────────────
# Symptoms: /health/ready returns models_loaded=false, /simulate returns 503
# RTO: 10 min

## Step 1: Check model files exist
#   ls -la models/trained/*.pth
# If missing, re-run training:
#   cd backend/core && poetry run python app/training/train_stress_model.py

## Step 2: If models are corrupted, fall back to heuristics
# The API still works without ML models (uses baseline heuristics).
# Set SINDIO_USE_CORE=1 in the Mock API.    

## Step 3: Restart the ML Core pod/service
#   docker compose restart core
# Or in K8s:
#   kubectl rollout restart deployment/sindio-rag -n sindio

# ── 4. Railway / Platform Outage ──────────────────────────────
# Symptoms: All Railway services unreachable
# RTO: 15 min (via DNS failover)

## Step 1: Verify Railway status page
#   https://status.railway.app/

## Step 2: Activate DNS failover to secondary backend
# If you have a secondary deployment (e.g., Render, Fly.io):
#   Update Cloudflare / Route53 DNS A record to point to secondary IP

## Step 3: Notify users via status page
#   Update https://<your-status-page>.com with incident details

# ── 5. Complete Infrastructure Loss (Region Failure) ───────────
# Symptoms: Entire AWS region down, all services unreachable
# RTO: 2 hours (cross-region DR)

## Step 1: Activate cross-region DR plan
#   terraform plan -var-file=prod.tfvars -target=module.eks_secondary
#   terraform apply -var-file=prod.tfvars -target=module.eks_secondary

## Step 2: Restore DB from S3 cross-region replication
#   aws s3 cp s3://sindio-prod-backups-eu-west-1/backups/latest.sql.gz /tmp/
#   ./scripts/restore_db.sh /tmp/latest.sql.gz

## Step 3: Update DNS to point to DR region
#   Route53 health checks should auto-failover if configured.

## Step 4: Notify stakeholders
#   PagerDuty / Opsgenie incident
#   Slack #incidents channel
#   Email to ops@sindio.urban

# ── 6. Contact List ────────────────────────────────────────────
# Primary On-Call:    +254-XXX-XXX-XXXX (ops@sindio.urban)
# Secondary On-Call:  +254-XXX-XXX-XXXX (dev@sindio.urban)
# Platform (Railway):   support@railway.app
# Cloud (AWS):          AWS Support (Business plan)
# Domain Registrar:     Cloudflare Enterprise Support
