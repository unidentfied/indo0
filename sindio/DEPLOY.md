# Sindio Deployment Guide

This document covers deploying the Sindio stack (backend + frontend) to production.

## Architecture

| Layer | Platform | URL Pattern |
|-------|----------|-------------|
| Mock API | Railway | `https://<service>.up.railway.app` |
| ML Core | Railway (same project) | `https://<service>.up.railway.app` |
| Frontend SPA | Netlify (via GitHub Actions) | `https://<site>.netlify.app` |

## 1. Mock API (Railway)

The mock API (`sindio/backend/app/`) is the default deployed backend. It serves endpoints directly and can proxy to the ML Core.

Railway does **not** auto-deploy from this repo. Create the service manually in the Railway dashboard, set Builder = Dockerfile, and configure environment variables before first deploy.

### Required Railway Environment Variables

Set these in your Railway **mock API service** dashboard:

| Variable | Required | Example |
|----------|----------|---------|
| `CORS_ORIGINS` | **Yes** | `https://sindio.netlify.app,http://localhost:4000` |
| `SINDIO_SKIP_RASTER` | Yes | `1` |
| `SINDIO_USE_CORE` | Yes | `0` (set to `1` when ML Core is live) |
| `PORT` | Auto | Railway injects this automatically |

**Optional but recommended:**

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (Railway auto-injects this if you add a Postgres service) |
| `REDIS_URL` | Redis connection string (Railway auto-injects this if you add a Redis service) |
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Individual PostgreSQL params (used if `DATABASE_URL` is not set) |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | Individual Redis params (used if `REDIS_URL` is not set) |
| `JWT_SECRET` | Auth token signing |
| `OPENAI_API_KEY` | AI features |

> **Critical:** `CORS_ORIGINS` must include your deployed Netlify URL exactly. If your Netlify site is `https://sindio-abc123.netlify.app`, add that to the comma-separated list.

### Health Check

Railway pings `/health` automatically. The backend should respond with:
```json
{"status": "ok", "source": "mock"}
```

## 2. ML Core (Railway — same project, separate service)

The ML Core (`sindio/backend/core/`) runs real ML inference, physics simulations (pandapower, EPANET, CTM), and the monitoring system. It is **optional for MVP** but required for real predictive analytics.

### How to deploy

1. In your **existing Railway project** (same one as the mock API), click **New** → **Empty Service**
2. Connect it to the same GitHub repo
3. In the service settings, set **Builder** to **Dockerfile**
4. Set **Dockerfile path** to `sindio/backend/core/Dockerfile.core`
5. Set **Root directory** to `/` (repo root)

> **No `railway.toml` or `railway.core.toml` exists in this repo.** Both services must be configured manually in the Railway dashboard (Builder = Dockerfile).

### Required Railway Environment Variables (ML Core)

| Variable | Required | Notes |
|----------|----------|-------|
| `CORS_ORIGINS` | Yes | Same Netlify frontend URL(s) |
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `CORE_PORT` | No | Defaults to `8081`; Railway injects `PORT` which overrides |
| `SINDIO_SKIP_RASTER` | Yes | `1` (skip 297MB WorldPop download) |
| `JWT_SECRET` | Yes | Any random secret string |

### Enabling Mock API → ML Core proxy

Once the ML Core is deployed and healthy:

1. In your **Mock API service** Variables, change:
   - `SINDIO_USE_CORE=1`
   - `CORE_URL=http://<ml-core-service-name>.railway.internal:8081`
   
   Railway provides internal DNS between services. You can find the internal hostname in the ML Core service settings under **Networking**.

2. Railway redeploys the mock API automatically.

## 3. Frontend (Netlify via GitHub Actions)

### Step 1: Create Netlify Site

1. Go to [netlify.com](https://netlify.com) and create a site from your GitHub repo.
2. **Do not** configure a build command in Netlify — GitHub Actions handles the build.
3. Note down your **Site ID** (Settings → General → Site details).
4. Generate a **Personal Access Token** (User settings → Applications → Personal access tokens).

### Step 2: Add GitHub Secrets

In your GitHub repo (Settings → Secrets and variables → Actions), add:

| Secret | Value |
|--------|-------|
| `NETLIFY_AUTH_TOKEN` | Your Netlify personal access token |
| `NETLIFY_SITE_ID` | Your Netlify site ID |

### Step 3: Add GitHub Variables (optional)

In GitHub Settings → Secrets and variables → Actions → Variables:

| Variable | Value |
|----------|-------|
| `VITE_API_BASE_URL` | Your Railway backend URL (e.g. `https://sindio-api.up.railway.app`) |

> If you don't set `VITE_API_BASE_URL` as a GitHub variable, the build falls back to the value in `.env.production`. Update that file with your actual Railway URL before first deploy.

### Step 4: Push to `main`

The `.github/workflows/frontend.yml` workflow will:
1. Install dependencies
2. Run TypeScript check + tests
3. Build the production bundle
4. Deploy `dist/` to Netlify

### Frontend Environment Files

| File | Purpose |
|------|---------|
| `.env.local` | Your local overrides (gitignored) |
| `.env.production` | Committed defaults for prod builds |
| `VITE_API_BASE_URL` | Full URL to Railway backend (no trailing slash) |

## 4. CI/CD Workflows

Three GitHub Actions workflows are configured:

### `.github/workflows/frontend.yml`
- Triggers on pushes to `main` affecting `sindio/frontend/**`
- Runs lint, tests, build
- Deploys to Netlify on success

### `.github/workflows/backend.yml`
- Triggers on pushes to `main` affecting `sindio/backend/**`
- **Mock API job:** validates Python syntax, lints Dockerfile, builds image, runs smoke test
- **ML Core job:** validates core Dockerfile syntax, lints with Hadolint (full build excluded from CI due to torch/transformers size)

## 5. Connecting Frontend ↔ Backend

### How it works

**Development (Vite dev server):**
- Frontend at `http://localhost:4000`
- Vite proxy sends `/api/*` and `/health` to `http://localhost:8080`
- No CORS issues (same origin via proxy)

**Production (Netlify → Railway):**
- Frontend at `https://*.netlify.app`
- API calls go directly to `https://*.railway.app/api/*`
- CORS preflight requests are handled by Railway backend
- Health checks go to `https://*.railway.app/health`

### Troubleshooting CORS

If you see browser console errors like:
```
Access to fetch at '...' from origin '...' has been blocked by CORS policy
```

1. Check Railway logs for the exact `Origin` header
2. Update `CORS_ORIGINS` in Railway dashboard to include it exactly
3. Redeploy backend (a variable change triggers auto-redeploy)

## 6. Railway Environment Variable Reference

Railway provides **connection strings** when you add a database service. The backend supports both formats:

| Format | Example | Used by |
|--------|---------|---------|
| Single URL | `DATABASE_URL=postgres://user:pass@host:5432/db` | Railway auto-injects this |
| Components | `DB_HOST=localhost`, `DB_PORT=5432`, etc. | Fallback if URL is not set |

The mock API and ML Core both prefer `DATABASE_URL` / `REDIS_URL` but fall back to individual components.

## 7. Post-Deploy Checklist

- [ ] Railway mock API service shows green health check
- [ ] `curl https://<railway-url>/health` returns `{"status": "ok"}`
- [ ] Netlify deploy log shows success
- [ ] Frontend loads and dashboard populates
- [ ] Browser DevTools → Network shows 200s for `/api/v1/*` calls
- [ ] (Optional) ML Core service health check passes
- [ ] (Optional) `/health/ready` shows `postgres: ok` and `redis: ok`

## 8. Monitoring & Alerting

The ML Core exposes `GET /api/v1/monitoring/health` which returns:

```json
{
  "scheduler": "running",
  "ingestion": "2026-07-03T12:00:00Z",
  "db": "ok",
  "sensor_readings_rows": 14500,
  "infrastructure_assets_rows": 320,
  "population_density_rows": 500,
  "ingestion_logs_rows": 12
}
```

### Configuring Railway Uptime Alerts

1. Go to your ML Core service in Railway → **Settings** → **Healthcheck**
2. Set **Healthcheck Path** to `/api/v1/monitoring/health`
3. Railway will ping this endpoint every 30 seconds
4. If the response is not `200 OK` for 3 consecutive checks, Railway marks the service as unhealthy and logs the failure

### Configuring External Uptime Monitoring

Any HTTP uptime monitor (UptimeRobot, BetterStack, PagerDuty) can ping:
```
GET https://<ml-core-url>/api/v1/monitoring/health
```

Expected response: HTTP 200 with `"db": "ok"` and `"scheduler": "running"`.
If `"scheduler"` is `"unavailable"`, apscheduler failed to start — check the deploy logs.
If `"db"` is `"unreachable"`, the database connection is broken — check `DATABASE_URL`.

## 9. Rollback

- **Backend:** Railway dashboard → Deployments → click previous deploy
- **Frontend:** Netlify dashboard → Deploys → click previous deploy
