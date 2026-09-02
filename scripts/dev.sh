#!/usr/bin/env bash
# Run the whole stack: FastAPI on :8000 and Next on :3000.
#
#   ./scripts/dev.sh
#
# The admin panel and the player both call the API, so the frontend alone is
# not enough to use the app. Starting them separately means remembering two
# setups; this remembers for you, and stops both together on Ctrl-C.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API="$ROOT/apps/api"
WEB="$ROOT/apps/web"

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

[ -d "$API/.venv" ] || fail \
"apps/api/.venv is missing. Once:

  cd apps/api && uv venv .venv && . .venv/bin/activate && uv pip install -e '.[dev]'"

[ -d "$WEB/node_modules" ] || fail \
"apps/web/node_modules is missing. Once:

  cd apps/web && npm install"

pids=()
cleanup() {
  trap - INT TERM EXIT
  # Kill the process groups: uvicorn --reload and next dev both fork children
  # that outlive a plain kill on the parent and then hold the ports.
  for pid in "${pids[@]:-}"; do
    [ -n "$pid" ] && kill -- "-$pid" 2>/dev/null || true
  done
}
trap cleanup INT TERM EXIT

echo "==> API   http://localhost:8000   (docs at /docs)"
setsid "$API/.venv/bin/uvicorn" app.main:app --reload --port 8000 \
  --app-dir "$API" &
pids+=($!)

# Wait for the API before starting the web server, so the first page load does
# not race it and show "Could not reach the API".
for _ in $(seq 1 40); do
  if curl -sS -o /dev/null -m 1 http://127.0.0.1:8000/healthz 2>/dev/null; then
    echo "    API is up"
    break
  fi
  sleep 0.5
done

if ! curl -sS -o /dev/null -m 2 http://127.0.0.1:8000/healthz 2>/dev/null; then
  echo "    API did not start — see the output above" >&2
fi

echo "==> Web   http://localhost:3000"
cd "$WEB"
setsid npm run dev &
pids+=($!)

wait
