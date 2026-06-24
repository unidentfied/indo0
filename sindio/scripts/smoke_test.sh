#!/usr/bin/env bash
#
# Sindio — Integration smoke test
#
# Starts the mock FastAPI backend on a random port, sends requests to
# every documented endpoint, and reports pass/fail.
#
# Usage:
#   ./scripts/smoke_test.sh          # auto-port, auto-venv
#   ./scripts/smoke_test.sh 8080     # specific port
#
set -euo pipefail

PORT="${1:-0}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="/tmp/sindio-smoke-venv"
VENV_PYTHON="$VENV_DIR/bin/python3"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass=0
fail=0

ok()  { echo -e "  ${GREEN}PASS${NC} $1"; pass=$((pass+1)); }
bad() { echo -e "  ${RED}FAIL${NC} $1 — $2"; fail=$((fail+1)); }

cleanup() {
  if [ -n "${SERVER_PID:-}" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  echo ""
  echo "Results: $pass passed, $fail failed"
  exit $fail
}
trap cleanup EXIT INT TERM

# ---- setup venv ----
if [ ! -f "$VENV_PYTHON" ]; then
  python3 -m venv "$VENV_DIR"
  "$VENV_PYTHON" -m pip install --only-binary=:all: -q \
    fastapi uvicorn httpx pydantic python-multipart starlette \
    numpy redis prometheus-client beautifulsoup4 python-dotenv 2>/dev/null
fi

# ---- start server ----
echo "Starting mock API..."
cd "$PROJECT_DIR/backend/app"
export PYTHONPATH=".:..:$PYTHONPATH"
"$VENV_PYTHON" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!
sleep 3

if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "ERROR: Server failed to start. Check dependencies."
  exit 1
fi

# resolve actual port (macOS: lsof, Linux: ss)
if command -v lsof >/dev/null 2>&1; then
  ACTUAL_PORT=$(lsof -p "$SERVER_PID" -i TCP -s TCP:LISTEN -Fn 2>/dev/null | grep 'n\*:' | head -1 | sed 's/.*://' || echo "")
fi
if [ -z "$ACTUAL_PORT" ] && command -v ss >/dev/null 2>&1; then
  ACTUAL_PORT=$(ss -tlnp 2>/dev/null | grep "pid=$SERVER_PID" | awk '{print $4}' | sed 's/.*://' | head -1 || echo "")
fi
if [ -z "$ACTUAL_PORT" ]; then
  # fallback: try common ports or parse uvicorn output
  ACTUAL_PORT="${PORT:-8080}"
  # if port was 0 (auto), check what uvicorn printed
  if [ "$ACTUAL_PORT" = "0" ] || [ -z "$ACTUAL_PORT" ]; then
    echo "WARNING: could not detect actual port, assuming 8080"
    ACTUAL_PORT="8080"
  fi
fi
BASE="http://127.0.0.1:$ACTUAL_PORT"
echo "Server running on $BASE"

# ---- helpers ----
get() {
  curl -sf -o /dev/null -w "%{http_code}" "$BASE$1" 2>/dev/null
}
get_json() {
  curl -sf "$BASE$1" 2>/dev/null
}
post() {
  curl -sf -o /dev/null -w "%{http_code}" -X POST "$BASE$1" \
    -H "Content-Type: application/json" -d "${2:-{}}" 2>/dev/null
}

# ---- test endpoints ----
echo ""
echo "Testing endpoints..."

# health
code=$(get "/health")
[ "$code" = "200" ] && ok "/health" || bad "/health" "got $code"

# dashboard metrics
code=$(get "/api/dashboard/metrics")
[ "$code" = "200" ] && ok "/api/dashboard/metrics" || bad "/api/dashboard/metrics" "got $code"

# dashboard alerts
code=$(get "/api/dashboard/alerts")
[ "$code" = "200" ] && ok "/api/dashboard/alerts" || bad "/api/dashboard/alerts" "got $code"

# infrastructure
code=$(get "/api/infrastructure/power")
[ "$code" = "200" ] && ok "/api/infrastructure/power" || bad "/api/infrastructure/power" "got $code"

code=$(get "/api/infrastructure/nonexistent")
[ "$code" = "404" ] && ok "/api/infrastructure/nonexistent → 404" || bad "/api/infrastructure/nonexistent" "got $code, expected 404"

# simulations
code=$(post "/api/simulations/run?network=power" '{"infrastructure_type":"power","stress_factor":"peak"}')
[ "$code" = "200" ] && ok "/api/simulations/run" || bad "/api/simulations/run" "got $code"

code=$(get "/api/simulations/status")
[ "$code" = "200" ] && ok "/api/simulations/status" || bad "/api/simulations/status" "got $code"

# v1 alerts
code=$(get "/api/v1/alerts")
[ "$code" = "200" ] && ok "/api/v1/alerts" || bad "/api/v1/alerts" "got $code"

# v1 monitor stress
code=$(get "/api/v1/monitor/stress")
[ "$code" = "200" ] && ok "/api/v1/monitor/stress" || bad "/api/v1/monitor/stress" "got $code"

# v1 spatial stress points
code=$(get "/api/v1/spatial/stress-points?infrastructure_type=power&limit=5")
[ "$code" = "200" ] && ok "/api/v1/spatial/stress-points" || bad "/api/v1/spatial/stress-points" "got $code"

# v1 next updates
code=$(get "/api/v1/next_updates")
[ "$code" = "200" ] && ok "/api/v1/next_updates" || bad "/api/v1/next_updates" "got $code"

# v1 scenario generate
code=$(post "/api/v1/scenario/generate" '{"prompt":"Nairobi population growth 2035 power water roads"}')
[ "$code" = "200" ] && ok "/api/v1/scenario/generate" || bad "/api/v1/scenario/generate" "got $code"

# metrics
code=$(get "/metrics")
[ "$code" = "200" ] && ok "/metrics" || bad "/metrics" "got $code"

echo ""
echo "All endpoints tested."
