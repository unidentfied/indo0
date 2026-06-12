# Sindio — Nairobi Urban Planning AI

Sindio is a local development environment for an AI-powered urban planning tool focused on Nairobi. It combines a Python (FastAPI) backend for predictive simulation APIs with a TypeScript/React frontend for the landing page and operational dashboard.

## Architecture

- **Backend**: Python 3.10+ / FastAPI — serves mock infrastructure metrics, alerts, and simulation endpoints.
- **Frontend**: TypeScript / React / Vite / Tailwind CSS — dark-themed landing page and interactive dashboard.
- **Assets**: All three reference images from `imagg/` are used in the site (landing preview, dashboard preview, map view).

## Pages

- `/` — Landing page (matches the first reference image)
- `/dashboard` — Operational dashboard combining Power Systems Analysis, GIS map visualization, predictive simulations, temporally spaced alerts, and stress test controls (matches the second and third reference images).

## Quick Start (localhost)

### 1. Backend

```bash
cd sindio/backend
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Backend will be available at: `http://localhost:8080`

### 2. Frontend

In a new terminal:

```bash
cd sindio/frontend
npm install
npm run dev
```

Frontend will be available at: `http://localhost:3000`

The Vite dev server proxies `/api` and `/health` to `http://localhost:8080` automatically.

## Key Features Implemented

- **Predictive Parameters Panel**: Thermal stress, population density toggles, grid redundancy failover switch.
- **Live Canvas Map**: Animated Nairobi grid visualization with pulsing nodes and traffic flow.
- **Critical Risk Feed**: Real-time alert cards with severity indicators.
- **Simulation Chart**: Projected impact bar chart (next 24h) with network selection.
- **Temporally Spaced Alerts**: Sidebar alert panel with critical/warning/advisory levels.
- **Stress Test Controls**: Run simulation button with mocked results and failure risk badges.
- **Responsive Layout**: Collapsible mobile menu, adaptive grid layouts.

## API Endpoints

- `GET /health` — Health check
- `GET /api/dashboard/metrics` — Infrastructure metrics
- `GET /api/dashboard/alerts` — Temporally spaced alerts
- `GET /api/infrastructure/{water|power|road}` — System status
- `POST /api/simulations/run?network={type}` — Run stress test simulation
- `GET /api/simulations/status` — Active simulation status
- `GET /api/predictive-params` — Predictive parameters

## Notes

- The frontend gracefully falls back to mock data if the backend is not running.
- All three reference images (`landing-reference.jpg`, `dashboard-reference.jpg`, `nairobi-planning.jpg`) are displayed in the landing page "Platform Previews" section and used as backgrounds/decorative elements.
