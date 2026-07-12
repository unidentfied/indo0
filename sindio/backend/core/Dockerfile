FROM python:3.11-slim

WORKDIR /workspace

COPY requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

COPY core/ /workspace/core/

ENV PYTHONPATH=/workspace:.:..\n
EXPOSE 8081

WORKDIR /workspace/core
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8081"]
