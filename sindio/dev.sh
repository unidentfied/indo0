#!/usr/bin/env bash
#
# Sindio — Local Development Launcher
#
# Starts the Python mock API backend (port 8080) and the Vite frontend
# dev server (port 4000).  Both run in the foreground; press Ctrl+C to stop.
#
# USAGE
#   ./dev.sh            Start both backend + frontend
#   ./dev.sh backend    Start only the backend
#   ./dev.sh frontend   Start only the frontend
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend/app"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VENV_PYTHON="/tmp/sindio-venv/bin/python3"
VENV_HASH_FILE="/tmp/sindio-venv/.reqhash"
REQUIRED_PACKAGES="fastapi uvicorn httpx pydantic python-multipart starlette numpy prometheus-client redis psycopg2-binary beautifulsoup4 python-dotenv structlog python-jose slowapi sqlalchemy opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi email-validator"
CURRENT_HASH=$(echo "$REQUIRED_PACKAGES" | { command -v sha256sum >/dev/null 2>&1 && sha256sum || shasum -a 256; } | cut -d' ' -f1)

if [ ! -f "$VENV_PYTHON" ] || [ ! -f "$VENV_HASH_FILE" ] || [ "$(cat "$VENV_HASH_FILE")" != "$CURRENT_HASH" ]; then
  echo "Creating/updating venv at /tmp/sindio-venv ..."
  python3 -m venv /tmp/sindio-venv --clear
  "$VENV_PYTHON" -m pip install --only-binary=:all: $REQUIRED_PACKAGES || {
    echo "ERROR: pip install failed. Check network connectivity."
    exit 1
  }
  echo "Installing rasterio (optional — skip with SINDIO_SKIP_RASTER=1 if it fails)..."
  "$VENV_PYTHON" -m pip install --only-binary=:all: rasterio 2>/dev/null || {
    echo "WARNING: rasterio install failed. Backend will use fallback coordinates."
    echo "  Set SINDIO_SKIP_RASTER=1 to suppress this warning."
    export SINDIO_SKIP_RASTER=1
  }
  echo "$CURRENT_HASH" > "$VENV_HASH_FILE"
fi

export PYTHONPATH=".:..:${PYTHONPATH:-}"
export CORE_PORT="${CORE_PORT:-8080}"
export VITE_API_URL="http://localhost:${CORE_PORT}"
export SINDIO_SKIP_RASTER="${SINDIO_SKIP_RASTER:-0}"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill 0 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

start_core() {
  echo "──────────────────────────────────────"
  echo " Sindio ML Core  → http://localhost:8081"
  echo "──────────────────────────────────────"
  cd "$SCRIPT_DIR/backend/core" || { echo "ERROR: Cannot cd to core"; exit 1; }
  "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload &
}

start_backend() {
  echo "──────────────────────────────────────"
  echo " Sindio Backend  → http://localhost:${CORE_PORT}"
  echo " API docs        → http://localhost:${CORE_PORT}/docs"
  echo "──────────────────────────────────────"
  cd "$BACKEND_DIR" || { echo "ERROR: Cannot cd to $BACKEND_DIR"; exit 1; }
  export CORE_URL="http://localhost:8081"
  export SINDIO_USE_CORE="1"
  "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "${CORE_PORT}" --reload
}

start_frontend() {
  echo "──────────────────────────────────────"
  echo " Sindio Frontend → http://localhost:4000"
  echo "──────────────────────────────────────"
  cd "$FRONTEND_DIR" || { echo "ERROR: Cannot cd to $FRONTEND_DIR"; exit 1; }
  node ./node_modules/vite/bin/vite.js
}

case "${1:-all}" in
  backend)
    start_core
    sleep 2
    start_backend
    ;;
  frontend)
    start_frontend
    ;;
  all)
    start_core
    sleep 2
    start_backend &
    BACKEND_PID=$!
    sleep 2
    if ! kill -0 $BACKEND_PID 2>/dev/null; then
      echo "ERROR: Backend process died during startup. Check the error above."
      exit 1
    fi
    start_frontend &
    wait
    ;;
  *)
    echo "Usage: ./dev.sh [backend|frontend|all]"
    exit 1
    ;;
esac
