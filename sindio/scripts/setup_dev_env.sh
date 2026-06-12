#!/usr/bin/env bash
# ============================================================
# Sindio — Development Environment Setup
# ============================================================
# Prerequisites: go, rust, python, node, docker
# Usage: chmod +x setup_dev_env.sh && ./setup_dev_env.sh
set -euo pipefail

echo "=== Sindio Monorepo Setup ==="

# ---- Python ----
echo "[1/5] Setting up Python core..."
cd backend/core
python3 -m venv venv
source venv/bin/activate
pip install poetry
poetry install --with dev
deactivate
cd ../..

# ---- Go ----
echo "[2/5] Setting up Go API..."
cd backend/api
go mod tidy
go build ./cmd/api/
cd ../..

# ---- Rust ----
echo "[3/5] Setting up Rust streaming..."
cd backend/streaming
cargo fetch
cargo check
cd ../..

# ---- Node / TypeScript ----
echo "[4/5] Setting up frontend..."
cd frontend
npm install
cd ..

# ---- Docker ----
echo "[5/5] Pulling Docker images..."
docker compose -f docker/docker-compose.yml pull postgres redis qdrant

# ---- Env file ----
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example — edit it with your credentials"
fi

echo "=== Setup complete ==="
echo "Start services: docker compose -f docker/docker-compose.yml up -d"
echo "Start frontend:  cd frontend && npm run dev"
echo "Start Go API:    cd backend/api && go run ./cmd/api/"
echo "Start Python:    cd backend/core && source venv/bin/activate && uvicorn app.main:app --port 8081 --reload"
echo "Start Rust:      cd backend/streaming && cargo run"
