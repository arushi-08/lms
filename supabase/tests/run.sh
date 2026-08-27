#!/usr/bin/env bash
# Applies the migrations to a scratch database and runs the RLS suite.
# Used by CI and by anyone touching a policy. Needs a local Postgres 16+.
#
#   ./supabase/tests/run.sh
#
# THIS SCRIPT DROPS AND RECREATES A DATABASE. It refuses to run against any
# host that is not local, because the obvious accident -- exporting your
# Supabase pooler URL to "test against the real thing" -- would otherwise
# attempt to drop your production database. A comment warning you not to do
# that is not a safeguard; this check is.
set -euo pipefail

DB="${PGDATABASE:-lms_rls_test}"
PSQL_USER="${PGUSER:-postgres}"
HOST="${PGHOST:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS="$HERE/../migrations"

case "$HOST" in
  ""|localhost|127.0.0.1|::1|/*) ;;   # empty, loopback, or a unix socket path
  *)
    if [ "${LMS_ALLOW_REMOTE_RESET:-}" != "1" ]; then
      echo "refusing to drop a database on non-local host '$HOST'." >&2
      echo "This script destroys the target database. If you genuinely mean to" >&2
      echo "reset a remote scratch database, set LMS_ALLOW_REMOTE_RESET=1." >&2
      echo "Never do that against a project holding real accounts or content." >&2
      exit 1
    fi
    echo "!! LMS_ALLOW_REMOTE_RESET=1 -- dropping '$DB' on remote host '$HOST'" >&2
    ;;
esac

# Guard the name too: a scratch run should never land on something that reads
# like a real database.
case "$DB" in
  postgres|production|prod|main|live)
    echo "refusing to drop a database named '$DB'." >&2
    exit 1
    ;;
esac

run() { psql -v ON_ERROR_STOP=1 -q -U "$PSQL_USER" -d "$DB" -f "$1"; }

echo "==> recreating $DB"
dropdb --if-exists -U "$PSQL_USER" "$DB"
createdb -U "$PSQL_USER" "$DB"

echo "==> applying shim + migrations"
run "$HERE/00_shim_supabase.sql"
for f in "$MIGRATIONS"/*.sql; do
  printf '    %s\n' "$(basename "$f")"
  run "$f"
done

echo "==> re-running seed to confirm idempotency"
run "$MIGRATIONS/0009_seed_dev.sql"

echo "==> RLS suite"
run "$HERE/01_rls_test.sql"

echo "==> ok"
