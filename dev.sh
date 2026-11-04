#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-localhost}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

if [[ -f backend/.venv/Scripts/python.exe ]]; then
  BACKEND_PYTHON="$ROOT_DIR/backend/.venv/Scripts/python.exe"
elif [[ -x backend/.venv/bin/python ]]; then
  BACKEND_PYTHON="$ROOT_DIR/backend/.venv/bin/python"
else
  echo "Backend environment not found. Run 'uv sync' from backend/ first." >&2
  exit 1
fi

if [[ ! -f frontend/node_modules/vite/bin/vite.js ]]; then
  echo "Frontend dependencies not found. Run 'npm install' from frontend/ first." >&2
  exit 1
fi

export PORT="$API_PORT"
export VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:${API_PORT}}"

if curl --fail --silent --show-error --max-time 2 \
  "http://${API_HOST}:${API_PORT}/health" >/dev/null 2>&1; then
  echo "A service is already responding at http://${API_HOST}:${API_PORT}." >&2
  echo "Refusing to reuse an unverified backend; stop it or set API_PORT to a free port." >&2
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  local status=$?
  trap - INT TERM EXIT
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]]; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
  return "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

(cd "$ROOT_DIR/backend" && exec "$BACKEND_PYTHON" -m uvicorn api.app:create_app \
  --factory --host "$API_HOST" --port "$API_PORT") &
BACKEND_PID=$!

(cd "$ROOT_DIR/frontend" && exec node node_modules/vite/bin/vite.js \
  --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort) &
FRONTEND_PID=$!

echo "Backend:  http://${API_HOST}:${API_PORT}"
echo "Frontend: http://localhost:${FRONTEND_PORT}"
echo "Press Ctrl+C to stop both services."

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
STATUS=$?
set -e
exit "$STATUS"
