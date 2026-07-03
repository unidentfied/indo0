FROM python:3.11-slim

WORKDIR /workspace

# ── System dependencies ──────────────────────────────────────────
# Required by torch, rasterio, psycopg2, shapely, pandapower, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libgeos-dev libgdal-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# ── Install Poetry ───────────────────────────────────────────────
RUN pip install --no-cache-dir poetry==1.7.1

# ── Copy dependency files first (layer caching) ────────────────
COPY sindio/backend/core/pyproject.toml sindio/backend/core/poetry.lock ./

# ── Install Python deps with BuildKit cache mount ──────────────
# Cache mount speeds up rebuilds by reusing Poetry cache between builds.
RUN --mount=type=cache,id=sindio-poetry,target=/root/.cache/pypoetry \
    poetry config virtualenvs.create false \
    && poetry install --no-dev --no-interaction --no-ansi \
    && pip install --no-cache-dir 'apscheduler>=3.10.0'

# ── Copy application code ──────────────────────────────────────
COPY sindio/backend/core/app/ ./app/

# ── Copy trained model weights and embeddings ──────────────────
COPY sindio/models/ ./models/

# ── Runtime environment ──────────────────────────────────────────
ENV PYTHONPATH=/workspace
ENV SINDIO_SKIP_RASTER=1
# CORS_ORIGINS, DATABASE_URL / DB_*, REDIS_URL / REDIS_* are
# injected at runtime by Railway / Render / etc.

EXPOSE 8081

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8081}
