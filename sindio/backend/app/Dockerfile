FROM python:3.11-slim

WORKDIR /workspace

# Install system dependencies (same as core)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libgeos-dev libgdal-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (using pip for mock service)
COPY backend/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Copy application code
COPY backend/app/ ./app/
# Copy the entire backend package so absolute imports work
COPY backend/ ./backend/

# Runtime env – make backend importable
ENV PYTHONPATH=/workspace
ENV SINDIO_SKIP_RASTER=1

EXPOSE 8080

WORKDIR /workspace/app
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
