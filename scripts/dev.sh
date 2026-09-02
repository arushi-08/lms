#!/usr/bin/env bash
# Run the whole stack: FastAPI on :8000 and Next on :3000.
#
#   ./scripts/dev.sh
#
# The admin panel and the player both call the API, so the frontend alone is
# not enough to use the app. This starts both and stops both on Ctrl-C.
#
# Portability notes, since this has to work on macOS as well as Linux:
#   * No setsid — it is util-linux only and absent on macOS.
#   * `set -m` gives each background job its own process group, so one signal
#     reaches uvicorn's reloader and next's child processes rather than
#     orphaning them holding the ports.
#   * No bash 4+ syntax: macOS still ships bash 3.2.
#   * The venv's scripts live in bin/ on macOS and Linux, Scripts/ on Windows.
#
# Ports can be overridden: API_PORT=8001 WEB_PORT=3001 ./scripts/dev.sh
set -euo pipefail
set -m

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

fail() { printf '\n%s\n' "$1" >&2; exit 1; }

[ -f "$API/.env" ] || fail \
"apps/api/.env is missing.

  cp apps/api/.env.example apps/api/.env

Then fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and DATABASE_URL.
DATABASE_URL is the pooled connection string from Supabase:
Project Settings > Database > Connection string > Transaction pooler (port 6543)."

[ -f "$WEB/.env.local" ] || fail \
"apps/web/.env.local is missing.

  cp apps/web/.env.example apps/web/.env.local

Then fill in NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY."

# Windows virtualenvs put executables in Scripts/ rather than bin/.
if [ -x "$API/.venv/bin/uvicorn" ]; then
  UVICORN="$API/.venv/bin/uvicorn"
elif [ -x "$API/.venv/Scripts/uvicorn.exe" ]; then
  UVICORN="$API/.venv/Scripts/uvicorn.exe"
else
  fail \
"The API virtualenv is missing or incomplete. Once:

  cd apps/api
  uv venv .venv
  . .venv/bin/activate        # .venv\\Scripts\\activate on Windows
  uv pip install -e '.[dev]'"
fi

[ -d "$WEB/node_modules" ] || fail \
"apps/web/node_modules is missing. Once:

  cd apps/web && npm install"

API_PID=""
WEB_PID=""

stop_one() {
  # Signal the whole process group where the shell gave the job its own
  # (thanks to `set -m`), falling back to the single process where it did not
  # — Git Bash on Windows being the case that needs the fallback.
  pid="$1"
  [ -n "$pid" ] || return 0
  kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
  trap - INT TERM EXIT
  echo ""
  echo "==> stopping"
  stop_one "$WEB_PID"
  stop_one "$API_PID"
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "==> API   http://localhost:$API_PORT   (docs at /docs)"
# Subshell + exec so $! is the uvicorn process itself, and so the working
# directory change does not leak into the web server started below.
( cd "$API" && exec "$UVICORN" app.main:app --reload --port "$API_PORT" ) &
API_PID=$!

# Wait for the API before starting the web server, so the first page load does
# not race it and show "Could not reach the API".
api_up=""
i=0
while [ "$i" -lt 40 ]; do
  if curl -sS -o /dev/null -m 1 "http://127.0.0.1:$API_PORT/healthz" 2>/dev/null; then
    api_up="yes"
    break
  fi
  # Has it already died? No point waiting out the full timeout.
  if ! kill -0 "$API_PID" 2>/dev/null; then
    break
  fi
  sleep 0.5
  i=$((i + 1))
done

if [ -n "$api_up" ]; then
  echo "    API is up"
else
  echo "    API did not start — see the output above" >&2
fi

echo "==> Web   http://localhost:$WEB_PORT"
( cd "$WEB" && exec npm run dev -- --port "$WEB_PORT" ) &
WEB_PID=$!

wait
