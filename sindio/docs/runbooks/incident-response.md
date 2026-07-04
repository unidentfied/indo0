# Sindio — Incident Response Runbook
=====================================

## Severity Levels

| Level | Name | Response Time | Who |
|-------|------|---------------|-----|
| SEV-1 | Critical (outage) | 15 min | Primary on-call |
| SEV-2 | Major (degraded) | 1 hour | Primary on-call |
| SEV-3 | Minor (noticeable) | 4 hours | Secondary on-call |
| SEV-4 | Low (cosmetic) | 24 hours | Best effort |

## SEV-1: Complete Outage

### Detection
- PagerDuty alert: `SindioHighErrorRate` > 5%
- Uptime monitor: no response in 3 consecutive checks
- Customer report via #incidents Slack

### Response
1. **Acknowledge** in PagerDuty (starts 15-min SLA clock)
2. **Join** incident bridge: `https://zoom.us/j/sindio-incident`
3. **Assess** scope via `kubectl get pods -n sindio` or Railway dashboard
4. **Check** dependent services: DB, Redis, KPLC API, Open-Meteo
5. **Mitigate**: If DB is down, failover to read replica (if configured)
6. **Communicate**: Post in #incidents every 30 min

### Escalation Path
- 15 min: Auto-escalate to secondary on-call
- 30 min: Escalate to engineering manager
- 1 hour: Escalate to CTO / CEO

## SEV-2: Degraded Performance

### Detection
- `SindioHighLatency` alert: p95 > 5s for 10 min
- `SindioFallbackRateSpike`: mock data ratio > 50%
- `SindioNoRealData`: zero real fetches in 2h

### Response
1. Check which upstream is failing: `curl https://<railway>/health/ready`
2. If mock ratio is high: data fetcher is failing → check `data_sources_candidates.json`
3. If latency is high: check DB query plans via pg_stat_statements
4. If Redis is slow: check memory usage and eviction policy

## Post-Incident Review (PIR)

Within 48 hours of SEV-1/2 resolution:
1. Schedule PIR meeting (30 min)
2. Fill out PIR template in `docs/postmortems/`
3. Create actionable tickets for each finding
4. Update runbooks if procedures were unclear

## On-Call Rotation

- Week 1: Alice (primary), Bob (secondary)
- Week 2: Bob (primary), Charlie (secondary)
- Week 3: Charlie (primary), Alice (secondary)

Handoff: Friday 5pm EAT, verify PagerDuty rotation is active.

## Playbooks by Alert

### `SindioFallbackRateSpike`
1. SSH / exec into the ML Core pod
2. Check logs: `kubectl logs deployment/sindio-rag -n sindio --tail=100`
3. Check upstream connectivity:
   - `curl https://api.open-meteo.com/v1/forecast?latitude=-1.30&longitude=36.82`
   - `curl https://overpass-api.de/api/interpreter` (small query)
4. If all upstreams fail: declare data-source outage, switch to full-mock mode

### `SindioHighErrorRate`
1. Check Railway / K8s pod status
2. Check if the error is localized to one endpoint via logs
3. If DB connection pool exhausted: scale connection pool or add read replica
4. If memory pressure: restart pod or scale replicas

### `SindioModelConfidenceCritical`
1. This means ML model predictions are unreliable (<50% confidence)
2. Check if model files exist: `ls /app/models/trained/*.pth`
3. If missing: re-run training pipeline
4. If present but low confidence: check input data quality (NaN values, stale data)

## Contact Information

| Role | Name | Phone | Slack |
|------|------|-------|-------|
| Primary On-Call | Alice | +254-XXX-XXX-0001 | @alice |
| Secondary On-Call | Bob | +254-XXX-XXX-0002 | @bob |
| Engineering Manager | Charlie | +254-XXX-XXX-0003 | @charlie |
| CTO | Diana | +254-XXX-XXX-0004 | @diana |
| AWS Support | — | — | AWS Console |
| Railway Support | — | support@railway.app | — |
| PagerDuty | — | — | @pagerduty |
