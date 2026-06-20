#!/usr/bin/env bash
#
# Sindio — Local Development Launcher
#
# Starts the Python FastAPI mock backend (port 8080) and the Vite frontend
# dev server (port 3000).  Both run in the foreground; press Ctrl+C to stop.
#
# USAGE
#   ./dev.sh            Start both backend + frontend
#   ./dev.sh backend    Start only the backend
#   ./dev.sh frontend   Start only the frontend
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend/core/app"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV_PYTHON="/tmp/sindio-venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
  echo "Creating venv at /tmp/sindio-venv ..."
  python3 -m venv /tmp/sindio-venv
  "$VENV_PYTHON" -m pip install --only-binary=:all: fastapi uvicorn httpx pydantic python-multipart starlette numpy prometheus-client
  echo "Installing rasterio (optional — skip with SINDIO_SKIP_RASTER=1 if it fails)..."
  "$VENV_PYTHON" -m pip install --only-binary=:all: rasterio 2>/dev/null || {
    echo "WARNING: rasterio install failed. Backend will use fallback coordinates."
    echo "  Set SINDIO_SKIP_RASTER=1 to suppress this warning."
    export SINDIO_SKIP_RASTER=1
  }
fi

export PYTHONPATH="$BACKEND_DIR:$SCRIPT_DIR/backend:${PYTHONPATH:-}"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill 0 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

start_backend() {
  echo "──────────────────────────────────────"
  echo " Sindio Backend  → http://localhost:${CORE_PORT:-8080}"
  echo " API docs        → http://localhost:${CORE_PORT:-8080}/docs"
  echo "──────────────────────────────────────"
  cd "$SCRIPT_DIR/backend"
  "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port ${CORE_PORT:-8080} --reload
}

start_frontend() {
  echo "──────────────────────────────────────"
  echo " Sindio Frontend → http://localhost:3000"
  echo "──────────────────────────────────────"
  cd "$FRONTEND_DIR"
  node ./node_modules/vite/bin/vite.js
}

case "${1:-all}" in
  backend)
    start_backend
    ;;
  frontend)
    start_frontend
    ;;
  all)
    start_backend &
    sleep 2
    start_frontend &
    wait
    ;;
  *)
    echo "Usage: ./dev.sh [backend|frontend|all]"
    exit 1
    ;;
esac
