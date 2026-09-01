#!/usr/bin/env bash
# Tests a sign-in directly against Supabase, bypassing the app entirely.
#
# The login form deliberately shows one generic message for every failure, so
# this exists to get at the real reason. If this succeeds, the problem is in
# the app; if it fails, the reply says exactly why.
#
#   ./scripts/check_auth.sh you@example.com 'your-password'
#
# Reads SUPABASE_URL and SUPABASE_ANON_KEY from the environment, or from
# apps/web/.env.local if you have not exported them.
set -euo pipefail

EMAIL="${1:-}"
PASSWORD="${2:-}"
if [ -z "$EMAIL" ] || [ -z "$PASSWORD" ]; then
  echo "usage: $0 <email> <password>" >&2
  exit 2
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HERE/../apps/web/.env.local"

URL="${SUPABASE_URL:-}"
KEY="${SUPABASE_ANON_KEY:-}"
if { [ -z "$URL" ] || [ -z "$KEY" ]; } && [ -f "$ENV_FILE" ]; then
  URL="${URL:-$(grep -E '^NEXT_PUBLIC_SUPABASE_URL=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"' ')}"
  KEY="${KEY:-$(grep -E '^NEXT_PUBLIC_SUPABASE_ANON_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"'"'"' ')}"
fi

if [ -z "$URL" ] || [ -z "$KEY" ]; then
  echo "set SUPABASE_URL and SUPABASE_ANON_KEY, or fill apps/web/.env.local" >&2
  exit 2
fi

echo "project: $URL"
echo

response=$(curl -sS -w '\n%{http_code}' \
  -X POST "$URL/auth/v1/token?grant_type=password" \
  -H "apikey: $KEY" \
  -H "Content-Type: application/json" \
  -d "{\"email\":$(printf '%s' "$EMAIL" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))'),\"password\":$(printf '%s' "$PASSWORD" | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))')}")

status=$(printf '%s' "$response" | tail -n1)
body=$(printf '%s' "$response" | sed '$d')

if [ "$status" = "200" ]; then
  echo "SIGN-IN OK (HTTP 200)"
  # Decode the token payload so you can confirm the access-token hook is on:
  # without it there is no user_role claim and admin RLS silently denies.
  printf '%s' "$body" | python3 -c '
import base64, json, sys
data = json.load(sys.stdin)
token = data.get("access_token", "")
part = token.split(".")[1] if token.count(".") == 2 else ""
if not part:
    print("  (no access token in the response)"); raise SystemExit
part += "=" * (-len(part) % 4)
claims = json.loads(base64.urlsafe_b64decode(part))
print("  sub      :", claims.get("sub"))
print("  email    :", claims.get("email"))
role = claims.get("user_role")
print("  user_role:", role if role else "MISSING -- the access token hook is not enabled")
'
  exit 0
fi

echo "SIGN-IN FAILED (HTTP $status)"
printf '%s\n' "$body"
echo
case "$body" in
  *"Invalid login credentials"*)
    echo "The email exists or does not, and the password does not match."
    echo "Most common cause: the user was created by invitation, which sets no"
    echo "password at all. Set one in Authentication > Users > the user > Reset password." ;;
  *"Email not confirmed"*)
    echo "Confirm the address, or tick Auto Confirm User when creating them." ;;
  *"email_provider_disabled"*|*"Email logins are disabled"*)
    echo "Email/password sign-in is switched off in Authentication > Providers > Email." ;;
  *"Invalid API key"*|*"invalid_api_key"*)
    echo "The anon key does not belong to this project. Recheck .env.local." ;;
esac
exit 1
