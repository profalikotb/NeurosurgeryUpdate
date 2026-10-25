#!/bin/sh
# Starts the backend (127.0.0.1:8000, private) and the website ($PORT, public) in one container.
set -e
APP="${APP_DIR:-/app}"
DATA="${ACADEMY_DATA_DIR:-/data}"
mkdir -p "$DATA"
export ACADEMY_DATA_DIR="$DATA"

# Internal API token: generated once and kept on the persistent disk (nothing to copy by hand).
if [ -z "$ACADEMY_API_TOKEN" ]; then
  [ -s "$DATA/.api-token" ] || python -c "import secrets; print(secrets.token_urlsafe(32))" > "$DATA/.api-token"
  ACADEMY_API_TOKEN="$(cat "$DATA/.api-token")"
  export ACADEMY_API_TOKEN
fi

cd "$APP/backend"
python -m uvicorn app.main:app --host 127.0.0.1 --port "${API_PORT:-8000}" &
API_PID=$!

cd "$APP/frontend"
PORT="${PORT:-3000}" HOSTNAME=0.0.0.0 BACKEND_URL="http://127.0.0.1:${API_PORT:-8000}" node server.js &
WEB_PID=$!

trap 'kill $API_PID $WEB_PID 2>/dev/null; exit 0' TERM INT
# If either process stops, stop the container so the host restarts it cleanly.
while kill -0 $API_PID 2>/dev/null && kill -0 $WEB_PID 2>/dev/null; do sleep 5; done
echo "A process stopped unexpectedly; exiting so the host restarts the service." >&2
kill $API_PID $WEB_PID 2>/dev/null
exit 1
