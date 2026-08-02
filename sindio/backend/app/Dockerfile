FROM python:3.11-slim

# Install system dependencies (same as core)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libgeos-dev libgdal-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy entire repository into container
COPY . /workspace

# Install Python dependencies (using pip for mock service)
RUN pip install --no-cache-dir -r /workspace/backend/requirements.txt

# Set working directory to mock app
WORKDIR /workspace/backend/app

# Runtime env – make backend importable
ENV PYTHONPATH=/workspace
ENV SINDIO_SKIP_RASTER=1

EXPOSE 8080

CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
