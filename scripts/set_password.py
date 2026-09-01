#!/usr/bin/env python3
"""Set a user's password directly, with no email involved.

Why this exists: Supabase's built-in email service allows only a couple of
messages an hour. It is a testing convenience, not a mail service. During setup
that is easy to exhaust, and once exhausted every password-reset route through
email is closed for an hour -- including the one you need to get in.

This uses the Admin API instead, which sends nothing and is not rate limited.

    export SUPABASE_URL=https://<ref>.supabase.co
    export SUPABASE_SERVICE_ROLE_KEY=<service role key>
    python3 scripts/set_password.py you@example.com 'a-strong-password'

The service role key bypasses every RLS policy in the database. Pass it through
the environment for one command; never put it in .env.local (that file is
compiled into the browser bundle), never commit it, and never paste it into a
chat or an issue. If it does leak, rotate it in the Supabase dashboard.

Exit codes: 0 done, 1 the API refused, 2 could not run.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 20


def api(url: str, key: str, path: str, *, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{url.rstrip('/')}{path}", data=data, method=method)
    request.add_header("apikey", key)
    request.add_header("Authorization", f"Bearer {key}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()[:400]
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw}
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def find_user(url: str, key: str, email: str) -> dict | None:
    """Walk the user list looking for this address.

    Paginated rather than filtered because the filter syntax has moved between
    GoTrue versions and a wrong filter silently returns everyone, which would
    make this script reset the wrong account.
    """
    wanted = email.strip().casefold()
    page = 1
    while page <= 50:
        status, payload = api(url, key, f"/auth/v1/admin/users?page={page}&per_page=200")
        if status == 0:
            raise SystemExit(f"could not reach the project: {payload.get('error')}")
        if status == 401:
            raise SystemExit("the key was rejected -- is that the service role key?")
        if status >= 400:
            raise SystemExit(f"admin API returned HTTP {status}: {payload}")

        users = payload.get("users", []) if isinstance(payload, dict) else []
        if not users:
            return None
        for user in users:
            if str(user.get("email", "")).strip().casefold() == wanted:
                return user
        page += 1
    return None


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: set_password.py <email> <new-password>", file=sys.stderr)
        return 2

    email, password = sys.argv[1], sys.argv[2]
    if len(password) < 10:
        print("use at least 10 characters", file=sys.stderr)
        return 2

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        print(
            "set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment.\n"
            "The service role key is in Supabase > Project Settings > API.",
            file=sys.stderr,
        )
        return 2

    user = find_user(url, key, email)
    if user is None:
        print(f"no user with email {email}", file=sys.stderr)
        print("Create one in Authentication > Users > Add user > Create new user.", file=sys.stderr)
        return 1

    status, payload = api(
        url,
        key,
        f"/auth/v1/admin/users/{user['id']}",
        method="PUT",
        # Confirm at the same time: an unconfirmed address cannot sign in even
        # with the right password, and that failure looks identical.
        body={"password": password, "email_confirm": True},
    )

    if status != 200:
        print(f"could not update the user (HTTP {status}): {payload}", file=sys.stderr)
        return 1

    print(f"password set for {email}")
    print("  confirmed:", bool(payload.get("email_confirmed_at")))
    print("\nNo email was sent. Sign in at /login.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
