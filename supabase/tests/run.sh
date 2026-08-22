#!/usr/bin/env bash
# Applies the migrations to a scratch database and runs the RLS suite.
# Used by CI and by anyone touching a policy. Needs a local Postgres 16+.
#
#   ./lms/supabase/tests/run.sh
#
# PGDATABASE defaults to a throwaway name; the script drops and recreates it,
# so never point it at anything you care about.
set -euo pipefail

DB="${PGDATABASE:-lms_rls_test}"
PSQL_USER="${PGUSER:-postgres}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS="$HERE/../migrations"

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
