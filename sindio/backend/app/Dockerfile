FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libgeos-dev libgdal-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy everything in backend/app/ (the build context) into /workspace
COPY . /workspace

WORKDIR /workspace

# Install dependencies from the local requirements.txt (already in this directory)
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# Runtime env
ENV PYTHONPATH=/workspace
ENV SINDIO_SKIP_RASTER=1

EXPOSE 8080

# Use shell form so ${PORT} is expanded at runtime
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
