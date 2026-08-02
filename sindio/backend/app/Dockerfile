FROM python:3.11-slim

# Install system dependencies (same as core)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libgeos-dev libgdal-dev postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install build tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy the whole repository into the image
COPY . /workspace
COPY ../backend/requirements.txt /workspace/backend/requirements.txt

# Install Python dependencies (mock service uses pip)
RUN pip install --no-cache-dir -r /workspace/backend/requirements.txt

# Set working directory to the mock app
WORKDIR /workspace/backend/app

# Runtime env – make backend importable
ENV PYTHONPATH=/workspace
ENV SINDIO_SKIP_RASTER=1

EXPOSE 8080

# Use JSON-formatted CMD to avoid signal handling issues
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT:-8080}"]
