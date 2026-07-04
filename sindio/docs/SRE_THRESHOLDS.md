# Sindio — Capacity Planning & SRE Thresholds
==============================================

## Scaling Triggers

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| API CPU | > 60% for 5m | > 80% for 5m | Scale replicas +1 |
| API Memory | > 70% for 5m | > 85% for 5m | Scale replicas +1 |
| API p95 Latency | > 1s for 10m | > 3s for 5m | Add read replica, optimize queries |
| API Error Rate | > 1% for 5m | > 5% for 3m | Page on-call, investigate |
| DB Connections | > 80% pool | > 95% pool | Scale connection pool, add replica |
| DB CPU | > 70% for 10m | > 90% for 5m | Optimize queries, scale instance |
| Redis Memory | > 70% for 10m | > 90% for 5m | Evict old keys, scale Redis |
| Disk Usage | > 70% for 1h | > 85% for 1h | Archive data, expand volume |
| Mock Data Ratio | > 30% for 30m | > 50% for 30m | Fix data fetchers, page on-call |
| Model Confidence | < 60% for 1h | < 50% for 1h | Retrain model, check input data |

## Resource Baselines (per 1000 concurrent users)

| Component | CPU | Memory | Replicas |
|-----------|-----|--------|----------|
| Mock API | 250m | 256Mi | 2 |
| ML Core | 1000m | 2Gi | 1 |
| Frontend | 100m | 128Mi | 2 |
| PostgreSQL | 500m | 1Gi | 1 (primary) |
| Redis | 250m | 512Mi | 1 |
| Celery Worker | 500m | 1Gi | 2 |

## HPA Configuration

| Service | Min | Max | Target CPU |
|---------|-----|-----|------------|
| sindio-api | 2 | 10 | 70% |
| sindio-rag | 1 | 6 | 70% |
| sindio-frontend | 2 | 8 | 60% |

## Database Scaling

### Read Replica Thresholds
- Add replica when primary CPU > 70% for 10 minutes
- Add replica when read query latency p95 > 500ms
- Maximum replicas: 3

### Connection Pool
- Primary: pool_size=20, max_overflow=10
- Read replica: pool_size=15, max_overflow=5
- Total connections: 50 (primary) + 45 per replica

## Cost Guardrails

| Service | Monthly Budget Alert | Monthly Hard Stop |
|---------|---------------------|---------------------|
| AWS EKS | $500 | $1000 |
| AWS RDS | $300 | $600 |
| Railway | $100 | $200 |
| Netlify | $50 | $100 |
| HERE API | $50 | $100 |

## Incident Severity by Metric

| Metric Pattern | SEV | Response |
|----------------|-----|----------|
| All metrics normal | — | — |
| 1 metric critical | SEV-2 | 1 hour |
| 2+ metrics critical | SEV-1 | 15 min |
| Complete data source failure | SEV-1 | 15 min |
| Model completely unavailable | SEV-1 | 15 min |
