# Sindio Production-Readiness Audit — Ruthless Findings

> **Date:** 2026-07-06
> **Scope:** Full-stack urban-planning AI monorepo (backend, frontend, infra, CI/CD, security, testing)
> **Method:** Code review, config analysis, dependency inspection, architectural review

---

## Legend
- **P0** — Critical: Will cause production outage, data loss, security breach, or compliance violation if deployed.
- **P1** — High: Will cause degraded reliability, scalability bottlenecks, or major operational pain.
- **P2** — Medium: Technical debt, maintainability issues, missing observability.

---

## P0 — CRITICAL

### P0-1. LIVE SECRETS COMMITTED TO `.env`
**File:** `sindio/.env`
**What:** The `.env` file contains live production secrets and API keys:
- `OPENAI_API_KEY=sk-proj-...`
- `MAPBOX_ACCESS_TOKEN=pk.eyJ1IjoiaW5kbz...`
- `HF_API_TOKEN=hf_AOHR...`
- `SERPAPI_KEY=1a4ca...`
- `QDRANT__SERVICE__JWT_SECRET=19fd46a7...`
- Database, Redis, Elasticsearch passwords
- `JWT_SECRET_KEY=your-secret-key-here` (placeholder but tracked)

**Why it matters:** `.env` is listed in `.gitignore` but the file is **already tracked** by git (has committed history). Even if removed now, it exists in git history forever. Any contributor with repo access has these keys. Rotating all keys is mandatory before any production deployment.

**Fix:**
1. Immediately rotate **all** API keys, database passwords, and tokens.
2. Run `git filter-repo` or BFG Repo-Cleaner to purge `.env` from entire git history.
3. Add `.env` to `.gitignore` (already there) but enforce pre-commit hooks (e.g., `git-secrets`, `truffleHog`) to block future commits.
4. Store secrets in a vault (AWS Secrets Manager, HashiCorp Vault, or Doppler) — never in repo.

---

### P0-2. `backend/app/.deps/` — 34 MB Vendored Dependencies with Broken Binaries
**File:** `sindio/backend/app/.deps/`
**What:** A 34 MB directory containing 1,604 vendored Python packages. Critical packages are **missing**, and present ones contain CPython 3.9 Darwin `.so` files that will fail on any Linux container or different Python version.

**Missing from `.deps` (required by code):**
- `python-jose` / `jose` — JWT auth (`app/core/auth.py`)
- `slowapi` — Rate limiting (`app/core/limiter.py`)
- `limits` — Rate-limit dependency of slowapi
- `wrapt` — Dependency of limits
- `structlog` — Structured logging (`app/core/logging_config.py`)
- `sniffio` — Async detection
- `psycopg2` — PostgreSQL driver
- `beautifulsoup4` / `bs4` — Web scraping (`app/scraper.py`)
- `h11`, `anyio` — HTTP/async networking

**Broken in `.deps`:**
- `fastapi` — Circular imports (`from fastapi import APIRouter` fails)
- `pydantic_core` — Compiled for CPython 3.9 Darwin only; will crash on Linux
- `numpy` — Same architecture mismatch
- `pydantic` — Version mismatch with `pydantic_core`

**Why it matters:** The application **cannot start** in a container. Even locally, imports fail. The `.deps` directory has been committed to git, bloating the repo. This is a deployment blocker.

**Fix:**
1. Delete `backend/app/.deps/` entirely.
2. Use standard `pip install -r requirements.txt` in Dockerfiles.
3. Pin exact versions in `requirements.txt` and `pyproject.toml`.
4. Add `backend/app/.deps/` to `.gitignore`.
5. Use multi-stage Docker builds to keep images small.

---

### P0-3. Docker Healthchecks Use `curl` but `curl` is Not Installed
**File:** `sindio/docker/docker-compose.yml` (lines 75, 98)
**What:** Both `core` and `app` services define:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8081/health"]
```
However, `Dockerfile.core` and `Dockerfile.app` use `python:3.11-slim` which does **not** include `curl`.

**Why it matters:** Docker Compose will mark these containers as **unhealthy**, triggering restart loops, deployment failures, and cascading service unavailability. Orchestrators (Swarm, K8s) rely on healthchecks for load-balancer membership.

**Fix:**
- Option A: Install `curl` in Dockerfiles: `RUN apt-get update && apt-get install -y curl`
- Option B (better): Replace `curl` with a Python healthcheck script using built-in `urllib` or `python -c`:
  ```yaml
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8081/health')"]
  ```

---

### P0-4. K8s ConfigMap Uses Invalid Shell Variable Interpolation
**File:** `sindio/k8s/01-configmap.yaml` (line 15)
**What:**
```yaml
CELERY_BROKER_URL: "redis://$(REDIS_HOST):$(REDIS_PORT)/0"
```
Kubernetes ConfigMaps do **not** resolve `$(VAR)` syntax. This is shell interpolation, not K8s template syntax. The literal string `redis://$(REDIS_HOST):$(REDIS_PORT)/0` will be injected into pods.

**Why it matters:** Celery workers will fail to connect to Redis, causing all background tasks (data ingestion, playbook execution, exports) to queue indefinitely and fail. The system appears healthy but is actually dead for async workloads.

**Fix:**
- Use explicit values: `redis://sindio-redis:6379/0`
- Or use K8s downward API / env var substitution in the Deployment spec, not the ConfigMap.

---

### P0-5. GDPR Deletion Logic Has Per-Table `rollback()` That Undoes Previous Deletions
**File:** `sindio/backend/app/routers/privacy.py` (lines 77–95)
**What:** The `delete_user_data` function iterates over tables and calls `conn.rollback()` **inside the loop** after each deletion:
```python
for table in tables:
    try:
        conn.execute(text(...))
        conn.commit()
    except Exception:
        conn.rollback()  # <-- rolls back the ENTIRE transaction
```

**Why it matters:** If the first 3 tables delete successfully and the 4th fails, `rollback()` undoes **all** previous deletions. This is a catastrophic data-privacy violation: you tell the user their data is deleted, but it isn't. This violates GDPR Article 17 (Right to Erasure) and exposes the organization to regulatory fines.

**Fix:**
- Use **one** transaction for the entire operation. Remove `conn.commit()` from the loop.
- Only commit after all deletions succeed. If any fail, the entire transaction rolls back, and you return a 500 error (do NOT claim success).
- Add comprehensive tests for partial-failure scenarios.

---

### P0-6. Duplicate Migration Number Causes Undefined Ordering
**Files:**
- `sindio/backend/migrations/012_feedback_table.sql`
- `sindio/backend/migrations/012_playbook_executions.sql`

**What:** Two migrations share the same sequence number `012`. Migration runners (Alembic, Flyway, golang-migrate) rely on strict ordering. Duplicate numbers create undefined behavior — one may run, both may run, or neither, depending on the runner and filesystem ordering.

**Why it matters:** Database state becomes non-deterministic. In production, this can lead to missing tables, failed deployments, or schema drift between environments.

**Fix:**
- Rename one to `013_playbook_executions.sql`.
- Verify no other duplicates exist: `ls migrations/ | sort | uniq -d`

---

### P0-7. No Authentication on Mock API Routers
**File:** `sindio/backend/app/main.py`
**What:** The FastAPI application includes `api_mock_router` with **no auth dependency**:
```python
app.include_router(api_mock_router, prefix="/api/v1")
```
This exposes endpoints like `/api/v1/health`, `/api/v1/zones`, `/api/v1/indicators` without any JWT validation.

**Why it matters:** Unauthenticated access to health checks is acceptable, but unauthenticated access to data endpoints (zones, indicators, feedback) leaks sensitive urban-planning data and allows anonymous write operations (feedback, execution requests).

**Fix:**
- Add `dependencies=[Depends(require_auth)]` to all non-public routers.
- Keep `/health` and `/metrics` public.
- Document which endpoints are intentionally public.

---

## P1 — HIGH

### P1-1. Frontend Bakes `VITE_API_KEY` into the Bundle
**File:** `sindio/frontend/src/services/api.ts`
**What:**
```typescript
const API_KEY = import.meta.env.VITE_API_KEY || "";
const HEADERS = { "x-api-key": API_KEY };
```
Vite inlines all `VITE_*` env vars into the built JavaScript bundle at build time. The API key becomes visible to any user who opens DevTools → Sources.

**Why it matters:** API keys are no longer secrets. Anyone can extract the key and abuse backend APIs, leading to quota exhaustion, data exfiltration, or unauthorized actions.

**Fix:**
- Remove API-key-based auth from frontend-to-backend calls.
- Use **HTTP-only cookies** with JWT sessions (set by backend on login).
- If API keys are needed for external integrations, proxy them through a backend endpoint.

---

### P1-2. K8s Frontend `nginx-exporter` Has Resource Requests but No Limits
**File:** `sindio/k8s/04-deployments.yaml` (frontend deployment, nginx-exporter container)
**What:** The `nginx-exporter` sidecar has:
```yaml
resources:
  requests:
    memory: "16Mi"
    cpu: "10m"
```
But no `limits` block.

**Why it matters:** Without limits, a memory leak or CPU spike in the exporter can exhaust node resources, causing OOM kills of other pods or node pressure eviction. This is a classic multi-tenant cluster stability issue.

**Fix:**
```yaml
resources:
  requests:
    memory: "16Mi"
    cpu: "10m"
  limits:
    memory: "64Mi"
    cpu: "100m"
```

---

### P1-3. K8s ConfigMap Contains Placeholder OpenSearch Endpoint
**File:** `sindio/k8s/01-configmap.yaml` (line 19)
**What:**
```yaml
OPENSEARCH_ENDPOINT: "https://vpc-sindio-opensearch-xxxxxxxxx.us-east-1.es.amazonaws.com"
```
The `xxxxxxxxx` is a literal placeholder.

**Why it matters:** Any service attempting to connect to OpenSearch will fail with DNS resolution errors. If this is deployed as-is, search/indexing features are completely broken.

**Fix:**
- Replace with the actual OpenSearch endpoint.
- Use Terraform outputs or external secrets management to inject the real endpoint at deploy time.

---

### P1-4. K8s API Service Missing `api` Selector in Ports
**File:** `sindio/k8s/02-services.yaml` (API service, line 16)
**What:**
```yaml
selector:
  app: api
ports:
  - name: http
    port: 80
    targetPort: 8080
```
The `ports` block lacks `app: api` alignment? Actually the selector is correct, but the service exposes port 80 → 8080 while the deployment uses `containerPort: 8080`. This is fine.

Wait — re-examining: the **real** issue is that the `api` service in `02-services.yaml` has selector `app: api`, but in `04-deployments.yaml` the API deployment is named `sindio-api` with label `app: api` — this matches.

Actually the P1 issue is: **K8s service has no session affinity or readiness probe gate.** The service will send traffic to pods that are not yet ready. But more critically:

**File:** `sindio/k8s/04-deployments.yaml` — API deployment has `livenessProbe` but **no `readinessProbe`**.

**Why it matters:** Kubernetes will route traffic to pods that are still starting up (DB connections not initialized, models not loaded). This causes 502/503 errors during rolling updates and scale-ups.

**Fix:**
```yaml
readinessProbe:
  httpGet:
    path: /api/v1/health
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
```

---

### P1-5. Missing `pytest-asyncio` in Requirements — Async Tests Cannot Run
**Files:** `sindio/backend/requirements.txt`, `sindio/backend/app/requirements.txt`
**What:** The test suite contains 24 async tests using `@pytest.mark.anyio` and `async def` test functions. Neither `requirements.txt` includes `pytest-asyncio` or `anyio`.

**Why it matters:** Running `pytest` will fail with `Fixture ... not found` or `async def` tests being skipped/ignored. The CI/CD pipeline (if it runs tests) will fail or falsely pass by not discovering async tests.

**Fix:**
```
pytest-asyncio>=0.23.0
anyio>=4.0.0
```
Add to both `requirements.txt` and `pyproject.toml`.

---

### P1-6. Terraform `.terraform.lock.hcl` Committed; `.terraform/` Directory Exists in Repo
**File:** `sindio/terraform/.terraform.lock.hcl`
**What:** The lock file is committed. The `.terraform/` directory (provider plugins, local state) also exists in the repo.

**Why it matters:**
- Lock files should be committed **only if** they are cross-platform. This one is Darwin-amd64 only.
- `.terraform/` contains binary provider plugins (hundreds of MB) and should never be in git.
- If CI/CD runs `terraform init`, it will conflict with the committed `.terraform/` directory.

**Fix:**
1. Add `.terraform/` to `.gitignore`.
2. Remove `.terraform/` from git history: `git rm -r --cached terraform/.terraform`
3. Keep `.terraform.lock.hcl` only if the team agrees; otherwise regenerate in CI.

---

### P1-7. EKS Cluster Version Pinned to 1.29 (Outdated)
**File:** `sindio/terraform/eks.tf` (line 7)
**What:**
```hcl
cluster_version = "1.29"
```

**Why it matters:** EKS 1.29 is approaching end-of-standard support. Running outdated Kubernetes versions means no security patches, missing features, and eventual forced upgrade by AWS.

**Fix:** Upgrade to EKS 1.31 or 1.32 (latest stable). Test all manifests for API version compatibility.

---

### P1-8. ArgoCD ApplicationSet References Non-Existent Repository
**File:** `sindio/k8s/argocd-applicationset.yaml` (line 13)
**What:**
```yaml
repoURL: git@github.com:unidentfied/indo0.git
```
This repository does not exist (typo in `unidentfied`, nonsensical repo name `indo0`).

**Why it matters:** ArgoCD will fail to sync the application. GitOps-based deployments are completely broken.

**Fix:**
```yaml
repoURL: git@github.com:your-org/sindio.git
```
Also verify SSH key secrets are configured in ArgoCD.

---

### P1-9. No Network Policies in Kubernetes
**File:** `sindio/k8s/` — no `NetworkPolicy` manifests.
**What:** All pods in the `sindio` namespace can communicate freely with each other and with the internet.

**Why it matters:** If one service is compromised (e.g., via a dependency vulnerability), the attacker has lateral movement access to the database, Redis, Elasticsearch, and OpenSearch. This violates the principle of least privilege.

**Fix:**
- Add `NetworkPolicy` to restrict ingress/egress:
  - `app` pods: egress only to `db`, `redis`, `elasticsearch`, `opensearch`, `core`.
  - `db` pods: ingress only from `app`, `worker`, `api`.
  - Block all internet egress except for `core` (if it needs external APIs).

---

### P1-10. No Pod Security Standards / SecurityContext
**File:** `sindio/k8s/04-deployments.yaml`
**What:** Containers run as root (no `securityContext`), with no `readOnlyRootFilesystem`, no `allowPrivilegeEscalation: false`, no `runAsNonRoot: true`.

**Why it matters:** Container escape vulnerabilities (e.g., runc CVEs) become trivial if the container runs as root with a writable root filesystem.

**Fix:**
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  readOnlyRootFilesystem: true
  allowPrivilegeEscalation: false
  seccompProfile:
    type: RuntimeDefault
```

---

## P2 — MEDIUM

### P2-1. `frontend/dist/` Build Artifacts Present in Working Tree
**File:** `sindio/frontend/dist/`
**What:** Vite build outputs are present locally but not tracked by git (they are in `.gitignore`).

**Why it matters:** This is minor but indicates developers are running `npm run build` locally and the artifacts are sitting in the working directory. It creates confusion about what is deployed.

**Fix:**
- Ensure `dist/` is in `.gitignore` (it is).
- Clean local builds: `rm -rf frontend/dist/`.
- All builds should happen in CI/CD only.

---

### P2-2. `netlify.toml` Has SPA Fallback but No API Proxy Rule
**File:** `sindio/netlify.toml`
**What:**
```toml
[[redirects]]
from = "/*"
to = "/index.html"
status = 200
```
There is no `/api/*` redirect rule to the backend.

**Why it matters:** API calls from the Netlify-hosted frontend will 404 because they fall through to the SPA fallback.

**Fix:**
```toml
[[redirects]]
from = "/api/*"
to = "https://api.sindio.com/api/:splat"
status = 200
force = true

[[redirects]]
from = "/*"
to = "/index.html"
status = 200
```

---

### P2-3. Go API Binary Committed to Repo
**File:** `sindio/backend/api/api` (25 MB)
**What:** A compiled Go binary is present in the source tree.

**Why it matters:** Binaries bloat the repo and are platform-specific (this is Darwin AMD64). They should be built in CI/CD.

**Fix:**
- `git rm --cached backend/api/api`
- Add `*.exe`, `api/api` to `.gitignore`.
- Build in Dockerfile or CI pipeline.

---

### P2-4. CORS Defaults to `localhost` if Env Var Missing
**File:** `sindio/backend/app/main.py`
**What:**
```python
origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
```

**Why it matters:** If `CORS_ORIGINS` is not set in production, the API will reject requests from the production frontend domain.

**Fix:**
- Fail fast on startup if `CORS_ORIGINS` is missing in non-local environments:
  ```python
  if os.getenv("ENV") == "production" and not os.getenv("CORS_ORIGINS"):
      raise RuntimeError("CORS_ORIGINS is required in production")
  ```

---

### P2-5. No Observability / Monitoring Stack
**What:** No Prometheus ServiceMonitors, no Grafana dashboards, no centralized logging (Fluent Bit / Fluentd), no distributed tracing (Jaeger / Zipkin), no alerting rules.

**Why it matters:** When the system breaks in production, you will be flying blind. No metrics means no SLOs, no autoscaling triggers, and no incident response data.

**Fix:**
- Add Prometheus `ServiceMonitor` CRDs for all services.
- Deploy Grafana with dashboards for API latency, error rates, queue depth.
- Add structured logging (JSON) and ship logs to OpenSearch / Loki.
- Add tracing middleware (OpenTelemetry) to FastAPI and Go API.

---

### P2-6. No Database Connection Pooling / Retry Logic
**File:** `sindio/backend/app/core/database.py`
**What:** SQLAlchemy engine is created with default pool settings. No retry logic for transient DB failures.

**Why it matters:** Under load or during a DB failover, connections will exhaust or fail permanently.

**Fix:**
```python
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"connect_timeout": 10, "options": "-c statement_timeout=30000"}
)
```

---

### P2-7. No Input Validation / Sanitization on Feedback Endpoint
**File:** `sindio/backend/app/routers/feedback.py`
**What:** The `feedback` endpoint accepts arbitrary JSON and stores it directly in PostgreSQL with no schema validation or sanitization.

**Why it matters:** Potential for NoSQL/JSON injection, oversized payloads causing DB bloat, or XSS if feedback is rendered in admin panels.

**Fix:**
- Define a Pydantic model for feedback with strict field types and `max_length` constraints.
- Validate and sanitize all inputs before storage.

---

### P2-8. Redis and PostgreSQL Exposed via LoadBalancer in Docker Compose
**File:** `sindio/docker/docker-compose.yml`
**What:** `redis` and `db` services have `ports:` mappings exposing them to the host:
```yaml
ports:
  - "5432:5432"
  - "6379:6379"
```

**Why it matters:** In production-like deployments (even staging), this exposes the database and cache to the public internet if the host has a public IP.

**Fix:**
- Remove `ports:` from `db` and `redis` in production compose files.
- Use internal Docker networks only.
- If local access is needed, create a separate `docker-compose.dev.yml`.

---

### P2-9. Terraform State Not Remote-Backed
**File:** `sindio/terraform/`
**What:** No `backend "s3"` or `backend "remote"` block is visible. Terraform state is likely local.

**Why it matters:** Local state files cannot be shared across a team. If the machine running Terraform is lost, so is the infrastructure state.

**Fix:**
```hcl
terraform {
  backend "s3" {
    bucket         = "sindio-terraform-state"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "sindio-terraform-locks"
  }
}
```

---

### P2-10. CI/CD Workflow Does Not Run Tests
**File:** `sindio/.github/workflows/ci.yml`
**What:** The workflow builds and pushes Docker images but does not run `pytest`, `go test`, or `npm test`.

**Why it matters:** Broken code can be deployed to production because there is no quality gate.

**Fix:**
- Add test jobs before build jobs:
  ```yaml
  test-backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r backend/requirements.txt
      - run: pytest backend/app/tests/
  ```
- Require test jobs to pass before Docker build.

---

## Summary Table

| ID | Severity | Category | Issue | Fix Effort |
|----|----------|----------|-------|------------|
| P0-1 | P0 | Security | Live secrets in `.env` | 1 day |
| P0-2 | P0 | Deployment | Broken vendored `.deps/` | 4 hours |
| P0-3 | P0 | Deployment | Healthcheck missing `curl` | 30 min |
| P0-4 | P0 | Deployment | K8s ConfigMap invalid syntax | 30 min |
| P0-5 | P0 | Compliance | GDPR deletion rolls back | 2 hours |
| P0-6 | P0 | Database | Duplicate migration number | 15 min |
| P0-7 | P0 | Security | No auth on mock routers | 2 hours |
| P1-1 | P1 | Security | API key baked into frontend | 4 hours |
| P1-2 | P1 | K8s | Missing resource limits | 15 min |
| P1-3 | P1 | Deployment | Placeholder OpenSearch endpoint | 15 min |
| P1-4 | P1 | K8s | No readinessProbe | 30 min |
| P1-5 | P1 | Testing | Missing `pytest-asyncio` | 15 min |
| P1-6 | P1 | IaC | Committed `.terraform/` | 30 min |
| P1-7 | P1 | IaC | EKS 1.29 outdated | 2 hours |
| P1-8 | P1 | GitOps | ArgoCD bad repo URL | 15 min |
| P1-9 | P1 | Security | No NetworkPolicies | 4 hours |
| P1-10 | P1 | Security | No securityContext | 2 hours |
| P2-1 | P2 | Hygiene | `dist/` artifacts present | 15 min |
| P2-2 | P2 | Deployment | Netlify missing API proxy | 15 min |
| P2-3 | P2 | Hygiene | Go binary in repo | 15 min |
| P2-4 | P2 | Config | CORS defaults to localhost | 30 min |
| P2-5 | P2 | Observability | No monitoring stack | 2 days |
| P2-6 | P2 | Reliability | No DB pooling / retry | 2 hours |
| P2-7 | P2 | Security | No feedback validation | 1 hour |
| P2-8 | P2 | Security | DB/Redis exposed in compose | 30 min |
| P2-9 | P2 | IaC | No remote Terraform state | 2 hours |
| P2-10 | P2 | CI/CD | No tests in CI | 2 hours |

---

## Recommended Execution Order

1. **Day 1 — Security Lockdown**
   - Rotate all secrets (P0-1).
   - Purge `.env` and `.deps/` from git history.
   - Add auth to all routers (P0-7).
   - Remove frontend API key (P1-1).

2. **Day 2 — Fix Deployment Blockers**
   - Delete `.deps/`, fix `requirements.txt`, rebuild Docker images (P0-2).
   - Fix healthchecks (P0-3).
   - Fix K8s ConfigMap interpolation (P0-4).
   - Fix migration numbering (P0-6).

3. **Day 3 — Harden Kubernetes**
   - Add NetworkPolicies (P1-9).
   - Add securityContexts (P1-10).
   - Add readinessProbes (P1-4).
   - Fix resource limits (P1-2).

4. **Day 4 — Infrastructure & GitOps**
   - Fix Terraform state backend (P2-9).
   - Upgrade EKS (P1-7).
   - Fix ArgoCD repo URL (P1-8).
   - Clean committed binaries (P2-3, P1-6).

5. **Day 5 — Reliability & Observability**
   - Fix GDPR deletion logic (P0-5).
   - Add DB pooling (P2-6).
   - Add monitoring stack (P2-5).
   - Add tests to CI (P2-10).

6. **Week 2 — Polish**
   - Input validation (P2-7).
   - CORS hardening (P2-4).
   - Netlify config (P2-2).
   - Docker Compose exposure (P2-8).

---

*End of audit.*
