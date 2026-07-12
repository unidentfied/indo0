FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY app/ /workspace/app/

ENV SINDIO_SKIP_RASTER=1
ENV PYTHONPATH=/workspace:.:..\n# CORS_ORIGINS and SINDIO_USE_CORE are injected at runtime by Railway.

EXPOSE 8080

WORKDIR /workspace/app
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
