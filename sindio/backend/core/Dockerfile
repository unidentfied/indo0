FROM python:3.11-slim

WORKDIR /workspace

COPY sindio/backend/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY sindio/backend/core/ /workspace/core/

ENV PYTHONPATH=/workspace:.:..

EXPOSE 8081

WORKDIR /workspace/core
CMD exec python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8081}
