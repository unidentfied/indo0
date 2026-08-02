# syntax=docker/dockerfile:1

# ---------- Builder ----------
FROM python:3.11-slim AS builder
WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libgeos-dev proj-bin proj-data libproj-dev gdal-bin libgdal-dev \
    && rm -rf /var/lib/apt/lists/*
ENV POETRY_HTTP_TIMEOUT=3600 PIP_DEFAULT_TIMEOUT=1200

# Install Poetry
RUN pip install --no-cache-dir poetry && \
    poetry config installer.max-workers 1

# Install project dependencies
COPY sindio/backend/core/pyproject.toml ./
COPY sindio/backend/core/poetry.lock ./
RUN POETRY_HTTP_TIMEOUT=1800 poetry config virtualenvs.create false && \
    poetry install --only main

# Copy application source code
COPY sindio/backend/ ./backend/
COPY sindio/app/ ./app/
COPY sindio/models/ /app/models
COPY sindio/data/ /app/data

# ---------- Runtime ----------
FROM python:3.11-slim AS runtime
WORKDIR /app

# Copy runtime dependencies and code
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /app /app

# Set PYTHONPATH for absolute imports
ENV PYTHONPATH=/app

# Create non‑root user
RUN adduser --disabled-password --gecos '' sindio && chown -R sindio:sindio /app
USER sindio

EXPOSE 8081

# Healthcheck endpoint
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/health/live')" || exit 1

# Start FastAPI app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081"]
