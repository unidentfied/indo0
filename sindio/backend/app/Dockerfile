FROM python:3.11-slim

WORKDIR /workspace

COPY sindio/backend/requirements.txt /workspace/app/requirements.txt
RUN pip install --no-cache-dir -r /workspace/app/requirements.txt

COPY sindio/backend/app/ /workspace/app/

ENV SINDIO_SKIP_RASTER=1
ENV PYTHONPATH=/workspace:.:..

EXPOSE 8080

WORKDIR /workspace/app
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
