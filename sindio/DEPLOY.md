# Sindio Deployment Guide

This document covers deploying the Sindio stack (backend + frontend) to production.

## Architecture

| Layer | Platform | URL Pattern |
|-------|----------|-------------|
| Backend API | Railway | `https://<service>.up.railway.app` |
| Frontend SPA | Netlify (via GitHub Actions) | `https://<site>.netlify.app` |

## 1. Backend (Railway)

Railway auto-deploys from `main` whenever you push. No manual deploy needed.

### Required Railway Environment Variables

Set these in your Railway project dashboard (they override `Dockerfile` defaults at runtime):

| Variable | Required | Example |
|----------|----------|---------|
| `CORS_ORIGINS` | **Yes** | `https://sindio.netlify.app,http://localhost:4000` |
| `SINDIO_SKIP_RASTER` | Yes | `1` |
| `SINDIO_USE_CORE` | Yes | `0` |
| `PORT` | Auto | Railway injects this automatically |

**Optional but recommended:**

| Variable | Purpose |
|----------|---------|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | PostgreSQL connection |
| `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD` | Redis connection |
| `JWT_SECRET` | Auth token signing |
| `OPENAI_API_KEY` | AI features |

> **Critical:** `CORS_ORIGINS` must include your deployed Netlify URL exactly. If your Netlify site is `https://sindio-abc123.netlify.app`, add that to the comma-separated list.

### Health Check

Railway pings `/health` automatically. The backend should respond with:
```json
{"status": "ok", "source": "mock"}
```

## 2. Frontend (Netlify via GitHub Actions)

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

### Step 3: Push to `main`

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

## 3. CI/CD Workflows

Two GitHub Actions workflows are configured:

### `.github/workflows/frontend.yml`
- Triggers on pushes to `main` affecting `sindio/frontend/**`
- Runs lint, tests, build
- Deploys to Netlify on success

### `.github/workflows/backend.yml`
- Triggers on pushes to `main` affecting `sindio/backend/**`
- Validates Python syntax
- Lints Dockerfile with Hadolint
- Builds Docker image and runs smoke test

## 4. Connecting Frontend ↔ Backend

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

## 5. Post-Deploy Checklist

- [ ] Railway service shows green health check
- [ ] `curl https://<railway-url>/health` returns `{"status": "ok"}`
- [ ] Netlify deploy log shows success
- [ ] Frontend loads without backend banner (or banner shows real data)
- [ ] Dashboard metrics populate from API
- [ ] Browser DevTools → Network shows 200s for `/api/v1/*` calls

## 6. Rollback

- **Backend:** Railway dashboard → Deployments → click previous deploy
- **Frontend:** Netlify dashboard → Deploys → click previous deploy
