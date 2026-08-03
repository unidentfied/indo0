FROM python:3.11-slim

# System dependencies (minimal — all Python deps install from pre-built wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements first (layer caching)
COPY sindio/backend/app/requirements.txt /workspace/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Copy the mock app into /workspace/app/ (preserving the package name)
COPY sindio/backend/app/ /workspace/app/

# Copy the backend package for cross-imports (e.g. from backend.core.app.logging)
COPY sindio/backend/ /workspace/backend/

WORKDIR /workspace

# Parent of app/ must be on PYTHONPATH so "from app.limiter" works
ENV PYTHONPATH=/workspace
ENV SINDIO_SKIP_RASTER=1

EXPOSE 8080

# Module path is now app.main since main.py lives at /workspace/app/main.py
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
