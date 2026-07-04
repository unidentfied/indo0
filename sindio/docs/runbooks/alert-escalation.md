# Sindio — Alert Escalation Policy
====================================

## Escalation Matrix

### SEV-1 (Critical: Service Down)
```
00:00  Alert fires (PagerDuty)
00:05  Page primary on-call (phone + push)
00:15  Auto-escalate to secondary on-call
00:30  Page engineering manager
01:00  Page CTO
```

### SEV-2 (Major: Degraded)
```
00:00  Alert fires (PagerDuty)
00:15  Page primary on-call
01:00  Page secondary on-call
02:00  Page engineering manager
```

### SEV-3 (Minor: Noticeable)
```
00:00  Alert fires (Slack #alerts, email)
04:00  Page primary on-call (if unacknowledged)
08:00  Page secondary on-call
```

## Notification Channels

| Severity | Primary | Secondary | Tertiary |
|----------|---------|-----------|----------|
| SEV-1 | PagerDuty push + phone | PagerDuty push + phone | PagerDuty push + email |
| SEV-2 | PagerDuty push | PagerDuty push | Slack DM |
| SEV-3 | Slack #alerts | Email | — |
| SEV-4 | Slack #alerts | — | — |

## Silence Policy

- Never silence SEV-1 alerts
- SEV-2 may be silenced for max 2 hours during known maintenance windows
- SEV-3/4 may be silenced with approval from EM during maintenance
- All silences must be documented in the incident log

## Weekend / Holiday Protocol

- Primary on-call is always staffed (no gaps)
- On-call rotation swaps are allowed with 72h advance notice
- Bank holidays: same rotation, same SLA
- Christmas week: reduced coverage (SEV-1 only, SEV-2 deferred to next business day)

## War Room Procedure

For SEV-1 incidents:
1. Create Zoom bridge: `https://zoom.us/j/sindio-incident`
2. Post bridge link in #incidents Slack
3. Assign roles:
   - **Incident Commander**: coordinates response, communicates externally
   - **Engineer Lead**: root cause analysis, implementation
   - **Communications**: customer updates, status page
4. Every 30 min: status update in #incidents
5. Do not deploy fixes directly to prod — use staging first unless customer-facing outage

## Post-Incident Follow-Up

- SEV-1/2: PIR within 48 hours
- SEV-3: PIR within 1 week
- SEV-4: Ticket created, no PIR required
- All PIRs must include: timeline, root cause, mitigation, prevention, action items
