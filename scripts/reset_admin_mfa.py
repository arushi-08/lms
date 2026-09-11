#!/usr/bin/env python3
"""Recover an admin account whose authenticator is lost.

Admin access requires that the account's verified TOTP factors are exactly the
one it was first set up with. That is what stops someone who has only the
password from enrolling an authenticator of their own and walking in. The cost of
that guarantee is this script: if the phone is gone, the account cannot fix
itself, because "I lost my second factor" is precisely what an attacker would
say.

So recovery deliberately requires something an attacker on the internet does not
have -- the database connection string.

    export DATABASE_URL=<the same value as apps/api/.env>
    python3 scripts/reset_admin_mfa.py admin@example.com            # show state
    python3 scripts/reset_admin_mfa.py admin@example.com --confirm  # reset it

What --confirm does: deletes every TOTP factor on the account and clears the pin,
so the next authenticator enrolled becomes the trusted one. Until that happens
the account has no admin access at all. Both facts are written to audit_log.

Run it, then immediately sign in and enroll a new authenticator. Between the two
the account is protected by its password alone, which is the state this whole
mechanism exists to avoid -- so do not leave it there.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

try:
    import asyncpg
except ImportError:
    sys.exit(
        "asyncpg is not installed. Run this from apps/api with its venv active:\n"
        "  cd apps/api && . .venv/bin/activate && python ../../scripts/reset_admin_mfa.py ..."
    )


async def main(email: str, confirm: bool) -> int:
    dsn = os.environ.get("DATABASE_URL", "").strip()
    if not dsn:
        print("set DATABASE_URL (the same value as apps/api/.env)", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn)
    try:
        profile = await conn.fetchrow(
            """
            select id, email, role::text as role, mfa_factor_id, mfa_verified_factors
            from profiles where lower(email) = lower($1)
            """,
            email,
        )
        if profile is None:
            print(f"no account with email {email}")
            return 1

        factors = await conn.fetch(
            """
            select id, status::text as status, friendly_name, created_at
            from auth.mfa_factors
            where user_id = $1 and factor_type::text = 'totp'
            order by created_at
            """,
            profile["id"],
        )

        print(f"account   {profile['email']}  ({profile['role']})")
        print(f"pinned    {profile['mfa_factor_id'] or '(none)'}")
        print(f"mirrored  {list(profile['mfa_verified_factors'] or [])}")
        print(f"factors   {len(factors)}")
        for factor in factors:
            marker = "<- pinned" if factor["id"] == profile["mfa_factor_id"] else ""
            name = factor["friendly_name"] or "unnamed"
            print(f"  {factor['id']}  {factor['status']:<10} {name}  {marker}")

        if profile["role"] != "admin":
            print("\nThis account is not an admin, so nothing here gates anything.")

        if not confirm:
            print("\nNothing changed. Re-run with --confirm to reset.")
            return 0

        # One transaction: a half-done reset would leave a pin pointing at a
        # factor that no longer exists, which reads as a break-in rather than a
        # recovery.
        async with conn.transaction():
            deleted = await conn.execute(
                "delete from auth.mfa_factors where user_id = $1 and factor_type::text = 'totp'",
                profile["id"],
            )
            # After the delete the trigger has already recomputed the mirror; the
            # pin is what it deliberately leaves alone, so clear it explicitly.
            await conn.execute(
                "update profiles set mfa_factor_id = null, mfa_verified_at = null where id = $1",
                profile["id"],
            )
            await conn.execute(
                """
                insert into audit_log (actor_id, action, entity_type, entity_id, diff)
                values ($1::uuid, 'mfa.reset_by_operator', 'profile', $2::text, $3::jsonb)
                """,
                profile["id"],
                str(profile["id"]),
                json.dumps(
                    {
                        "removed_factors": len(factors),
                        "previous_pin": str(profile["mfa_factor_id"])
                        if profile["mfa_factor_id"]
                        else None,
                    }
                ),
            )

        print(f"\nreset ({deleted}). Admin access is closed on this account until a new")
        print("authenticator is enrolled at /account/security. Do that now.")
        return 0
    finally:
        await conn.close()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--confirm"]
    if len(args) != 1:
        sys.exit(__doc__)
    raise SystemExit(asyncio.run(main(args[0], "--confirm" in sys.argv[1:])))
