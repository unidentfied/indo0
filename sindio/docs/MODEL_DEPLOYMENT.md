# Sindio — Model Versioning & Canary Deployment
# ==============================================

## Model Registry Structure

```
models/
├── trained/
│   ├── urban_stress_v1.20240115.pth
│   ├── urban_stress_v1.20240201.pth
│   ├── urban_stress_v2.20240301.pth
│   ├── mobility_v2.20240115.pth
│   └── water_demand_v1.20240115.pth
├── manifest.json          # Current production versions
└── experiments/           # A/B test candidates
    └── urban_stress_v2_experiment.pth
```

## Manifest Format

```json
{
  "production": {
    "urban_stress": {
      "version": "v1.20240201",
      "path": "s3://sindio-prod-models/models/v1.20240201/urban_stress_v1.pth",
      "metrics": {
        "test_mae": 0.127,
        "test_breach_acc": 0.878
      },
      "deployed_at": "2024-02-01T03:00:00Z"
    },
    "mobility": {
      "version": "v2.20240115",
      "path": "s3://sindio-prod-models/models/v2.20240115/mobility_v2.pth"
    },
    "water_demand": {
      "version": "v1.20240115",
      "path": "s3://sindio-prod-models/models/v1.20240115/water_demand_v1.pth"
    }
  },
  "canary": {
    "urban_stress": {
      "version": "v2.20240301",
      "traffic_percent": 5,
      "metrics": {
        "test_mae": 0.115,
        "test_breach_acc": 0.892
      }
    }
  }
}
```

## Deployment Strategy

### 1. Training → Validation
```bash
# Train new model
cd backend/core && python app/training/train_stress_model.py --epochs 100

# Validate against hold-out test set
python scripts/validate_model.py --model models/trained/urban_stress_v2.pth --test-data data/test/
```

### 2. Canary Deployment (5% traffic)
```bash
# Deploy new model to canary pods
kubectl set image deployment/sindio-core-canary \
  core=ghcr.io/sindio/sindio-simulator:urban-stress-v2-$(date +%Y%m%d)

# Monitor for 24 hours
# - Error rate < 1%
# - Latency p95 < 2s
# - Model confidence > 60%
```

### 3. Gradual Rollout
```bash
# Increase traffic: 5% → 25% → 50% → 100%
kubectl patch virtualservice sindio-core -p '{"spec":{"http":[{"route":[{"destination":{"host":"sindio-core","subset":"stable"},"weight":75},{"destination":{"host":"sindio-core","subset":"canary"},"weight":25}]}]}}'
```

### 4. Automatic Rollback Criteria
```yaml
rollback_conditions:
  - metric: error_rate
    threshold: "> 2%"
    duration: "5m"
  - metric: model_confidence
    threshold: "< 0.5"
    duration: "10m"
  - metric: p95_latency
    threshold: "> 5s"
    duration: "5m"
```

## A/B Testing Framework

```python
# In ModelRegistry.load_models()
import random

canary_traffic_pct = float(os.getenv("CANARY_TRAFFIC_PCT", "0"))
if random.random() < canary_traffic_pct / 100:
    model_path = self._get_canary_path(model_name)
else:
    model_path = self._get_production_path(model_name)
```

## CI/CD Integration

```yaml
# .github/workflows/model-deploy.yml
- name: Validate model
  run: python scripts/validate_model.py
- name: Deploy canary
  run: kubectl apply -f k8s/canary-deployment.yaml
- name: Wait for canary health
  run: |
    for i in {1..60}; do
      curl -f http://canary/health/ready && break
      sleep 30
    done
- name: Promote or rollback
  run: |
    if ./scripts/canary_health_check.sh; then
      kubectl patch deployment sindio-core -p '{"spec":{"template":{"spec":{"containers":[{"name":"core","image":"canary-image"}]}}}}'
    else
      kubectl rollout undo deployment/sindio-core-canary
    fi
```
