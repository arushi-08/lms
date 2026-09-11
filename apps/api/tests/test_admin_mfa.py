"""The admin second-factor gate, from the outside.

Every test here is an attempt to act as an admin without satisfying one of the
four conditions in ``require_admin``, made against a real admin route with a
genuine signed token. The interesting cases are not "no token" -- those are
covered elsewhere -- but the ones where the attacker holds something real: a
valid admin token from a password-only session, or a valid *aal2* token earned
with an authenticator they enrolled themselves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.security.deps import (
    MFA_ENROLLMENT_REQUIRED,
    MFA_FACTOR_MISMATCH,
    MFA_REQUIRED,
)
from tests.conftest import ADMIN, ADMIN_FACTOR, ALICE, token_for

pytestmark = pytest.mark.anyio

#: Any route behind require_admin will do; this one is a plain read.
ADMIN_ROUTE = "/api/admin/courses"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[AsyncClient]:
    from app.db import build_database
    from app.providers.video.factory import build_video_provider

    app = create_app(settings)
    database = build_database(settings)
    await database.connect()
    app.state.database = database
    app.state.video_provider = build_video_provider(settings)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as http:
            yield http
    finally:
        await database.disconnect()


@pytest.fixture
async def conn(settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(settings.database_url.get_secret_value())
    try:
        yield connection
    finally:
        await connection.close()


@pytest.fixture(autouse=True)
async def restore_factors(conn: asyncpg.Connection) -> AsyncIterator[None]:
    """Put the admin's factor state back exactly as seeded.

    These tests deliberately mangle it, and the trigger is what maintains the
    mirrored columns -- so the reset goes through the factor table rather than
    writing the profile columns directly, which is also a small check that the
    trigger works in both directions.
    """
    yield
    await conn.execute("delete from auth.mfa_factors where user_id = $1", ADMIN)
    await conn.execute("update profiles set mfa_factor_id = null where id = $1", ADMIN)
    await conn.execute(
        "insert into auth.mfa_factors (id, user_id, factor_type, status) "
        "values ($1, $2, 'totp', 'verified')",
        ADMIN_FACTOR,
        ADMIN,
    )
    await conn.execute("delete from audit_log")


async def add_factor(conn: asyncpg.Connection, *, status: str = "verified") -> UUID:
    factor_id = uuid4()
    await conn.execute(
        "insert into auth.mfa_factors (id, user_id, factor_type, status) "
        "values ($1, $2, 'totp', $3::auth.factor_status)",
        factor_id,
        ADMIN,
        status,
    )
    return factor_id


def bearer(**kwargs: object) -> dict[str, str]:
    token = token_for(ADMIN, "admin@example.test", "admin", **kwargs)  # type: ignore[arg-type]
    return {"Authorization": f"Bearer {token}"}


class TestSteppedUp:
    async def test_a_fully_set_up_admin_is_allowed(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        """The control. Without this the refusals below prove nothing."""
        assert (await client.get(ADMIN_ROUTE, headers=admin_auth)).status_code == 200

    async def test_one_factor_admin_is_refused(
        self, client: AsyncClient, conn, admin_auth_one_factor
    ) -> None:
        """A password-only -- or Google-only -- admin session.

        This is the case that makes enabling Google sign-in safe for an account
        that also happens to be an admin.
        """
        response = await client.get(ADMIN_ROUTE, headers=admin_auth_one_factor)
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_REQUIRED

    async def test_a_missing_aal_claim_counts_as_one_factor(
        self, client: AsyncClient, conn
    ) -> None:
        """A token minted before the claim existed must not read as stepped up."""
        import jwt as pyjwt

        from tests.conftest import JWT_SECRET

        full = token_for(ADMIN, "admin@example.test", "admin", aal="aal2")
        payload = pyjwt.decode(
            full, JWT_SECRET, algorithms=["HS256"], audience="authenticated",
            options={"verify_iss": False},
        )
        del payload["aal"]
        stripped = pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

        response = await client.get(
            ADMIN_ROUTE, headers={"Authorization": f"Bearer {stripped}"}
        )
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_REQUIRED

    async def test_an_unknown_aal_value_counts_as_one_factor(
        self, client: AsyncClient, conn
    ) -> None:
        response = await client.get(ADMIN_ROUTE, headers=bearer(aal="aal3"))
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_REQUIRED


class TestEnrollment:
    async def test_an_admin_with_no_factor_is_refused(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        await conn.execute("delete from auth.mfa_factors where user_id = $1", ADMIN)
        await conn.execute("update profiles set mfa_factor_id = null where id = $1", ADMIN)

        response = await client.get(ADMIN_ROUTE, headers=admin_auth)
        assert response.status_code == 403
        # A different screen from "enter your code", hence a different code.
        assert response.headers["X-MFA-Status"] == MFA_ENROLLMENT_REQUIRED

    async def test_an_unverified_factor_does_not_count(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        """Enrollment starts by creating an unverified factor.

        Half-finished setup must not open the door, or an attacker could reach
        admin routes by starting an enrollment and never completing it.
        """
        await conn.execute("delete from auth.mfa_factors where user_id = $1", ADMIN)
        await conn.execute("update profiles set mfa_factor_id = null where id = $1", ADMIN)
        await add_factor(conn, status="unverified")

        response = await client.get(ADMIN_ROUTE, headers=admin_auth)
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_ENROLLMENT_REQUIRED


class TestFactorPinning:
    async def test_an_extra_verified_factor_is_refused(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        """The attack this whole mechanism exists for.

        Someone with the admin's password enrolls their own authenticator and
        steps up with it. Supabase issues a real aal2 token -- there is nothing
        wrong with it. What gives them away is the account now holding two
        verified factors when it is trusted to hold exactly one.
        """
        await add_factor(conn)

        response = await client.get(ADMIN_ROUTE, headers=admin_auth)
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_FACTOR_MISMATCH

    async def test_removing_the_extra_factor_restores_access(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        """Recovery is deleting the intruder's factor, not re-enrolling yours."""
        intruder = await add_factor(conn)
        assert (await client.get(ADMIN_ROUTE, headers=admin_auth)).status_code == 403

        await conn.execute("delete from auth.mfa_factors where id = $1", intruder)
        assert (await client.get(ADMIN_ROUTE, headers=admin_auth)).status_code == 200

    async def test_losing_the_pinned_factor_is_refused(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        """Deleting the trusted factor does not reset the account to 'enroll anything'.

        If it did, deleting a factor would be the cheapest way past TOTP: remove
        the real one, enroll your own, step up, done.
        """
        await conn.execute("delete from auth.mfa_factors where id = $1", ADMIN_FACTOR)

        response = await client.get(ADMIN_ROUTE, headers=admin_auth)
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_FACTOR_MISMATCH

        # And enrolling a replacement does not silently become the trusted one.
        await add_factor(conn)
        response = await client.get(ADMIN_ROUTE, headers=admin_auth)
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_FACTOR_MISMATCH


class TestNonAdmins:
    async def test_a_student_learns_nothing_about_mfa(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        """A non-admin is refused for not being an admin, full stop.

        No X-MFA-Status header: the sequence of screens an admin sees is not
        information a student needs, and 'you would need 2FA' confirms the route
        is one an admin can reach.
        """
        response = await client.get(ADMIN_ROUTE, headers=alice_auth)
        assert response.status_code == 403
        assert "X-MFA-Status" not in response.headers
        assert response.json()["detail"] == "admin only"

    async def test_a_stepped_up_student_is_still_not_an_admin(
        self, client: AsyncClient, conn
    ) -> None:
        """aal2 is not a role. A student with TOTP enabled is still a student."""
        token = token_for(ALICE, "alice@example.test", "student", aal="aal2")
        response = await client.get(
            ADMIN_ROUTE, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "admin only"

    async def test_a_forged_role_claim_does_not_help(
        self, client: AsyncClient, conn
    ) -> None:
        """The role comes from the database, so claiming admin changes nothing.

        The token here is signed with the real key -- this is what a *legitimate*
        student's token would look like if the access-token hook were wrong.
        """
        token = token_for(ALICE, "alice@example.test", "admin", aal="aal2")
        response = await client.get(
            ADMIN_ROUTE, headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "admin only"


class TestStatusRoute:
    async def test_it_reports_a_satisfied_admin(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        response = await client.get("/api/admin/mfa", headers=admin_auth)
        assert response.status_code == 200
        assert response.json() == {
            "satisfied": True,
            "reason": None,
            "enrolled": True,
            "stepped_up": True,
            "verified_factor_count": 1,
        }

    async def test_it_is_reachable_while_blocked(
        self, client: AsyncClient, conn, admin_auth_one_factor
    ) -> None:
        """The whole point of the weaker gate on this route.

        An admin who cannot pass the second-factor check still has to be told
        which screen they need, so this route must answer where the others 403.
        """
        response = await client.get("/api/admin/mfa", headers=admin_auth_one_factor)
        assert response.status_code == 200
        body = response.json()
        assert body["satisfied"] is False
        assert body["reason"] == MFA_REQUIRED
        assert body["enrolled"] is True

    async def test_it_reports_enrollment_needed(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        await conn.execute("delete from auth.mfa_factors where user_id = $1", ADMIN)
        await conn.execute("update profiles set mfa_factor_id = null where id = $1", ADMIN)

        body = (await client.get("/api/admin/mfa", headers=admin_auth)).json()
        assert (body["satisfied"], body["reason"]) == (False, MFA_ENROLLMENT_REQUIRED)
        assert body["enrolled"] is False

    async def test_it_reports_a_mismatch(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        await add_factor(conn)
        body = (await client.get("/api/admin/mfa", headers=admin_auth)).json()
        assert (body["satisfied"], body["reason"]) == (False, MFA_FACTOR_MISMATCH)
        assert body["verified_factor_count"] == 2

    async def test_a_student_cannot_read_it(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        response = await client.get("/api/admin/mfa", headers=alice_auth)
        assert response.status_code == 403


class TestRotation:
    async def test_rotation_unpins_and_locks_until_re_enrolled(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        """Switching phones: unpin, then enroll the new authenticator.

        Between those two steps the account has no trusted factor and admin
        access is closed. Landing in the locked state is correct -- the
        alternative is a window where any factor would do.
        """
        response = await client.post("/api/admin/mfa/rotate", headers=admin_auth)
        assert response.status_code == 200
        assert response.json()["previous_factor_id"] == str(ADMIN_FACTOR)

        blocked = await client.get(ADMIN_ROUTE, headers=admin_auth)
        assert blocked.status_code == 403
        assert blocked.headers["X-MFA-Status"] == MFA_ENROLLMENT_REQUIRED

        # The new authenticator becomes the trusted one on verification.
        await conn.execute("delete from auth.mfa_factors where user_id = $1", ADMIN)
        replacement = await add_factor(conn)
        assert (await client.get(ADMIN_ROUTE, headers=admin_auth)).status_code == 200
        pinned = await conn.fetchval(
            "select mfa_factor_id from profiles where id = $1", ADMIN
        )
        assert pinned == replacement

    async def test_rotation_needs_the_current_factor(
        self, client: AsyncClient, conn, admin_auth_one_factor
    ) -> None:
        """Otherwise a stolen password alone could retire the real authenticator."""
        response = await client.post(
            "/api/admin/mfa/rotate", headers=admin_auth_one_factor
        )
        assert response.status_code == 403
        assert response.headers["X-MFA-Status"] == MFA_REQUIRED
        still_pinned = await conn.fetchval(
            "select mfa_factor_id from profiles where id = $1", ADMIN
        )
        assert still_pinned == ADMIN_FACTOR

    async def test_a_student_cannot_rotate(
        self, client: AsyncClient, conn, alice_auth
    ) -> None:
        response = await client.post("/api/admin/mfa/rotate", headers=alice_auth)
        assert response.status_code == 403

    async def test_rotation_is_audited(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        await client.post("/api/admin/mfa/rotate", headers=admin_auth)
        actions = [
            row["action"]
            for row in await conn.fetch(
                "select action from audit_log where actor_id = $1", ADMIN
            )
        ]
        assert "mfa.rotation_started" in actions


class TestContentAccess:
    async def test_a_one_factor_admin_does_not_see_drafts(
        self, client: AsyncClient, conn, admin_auth_one_factor
    ) -> None:
        """Viewing unpublished content is an admin power too.

        ``resolve_entitlement`` decides this one, not ``require_admin``, so it
        needs its own test -- a gate applied in one of two places is a gate with
        a hole in it.
        """
        lesson = await conn.fetchval("select id from lessons where slug = 'hidden'")
        response = await client.post(
            f"/api/lessons/{lesson}/playback", headers=admin_auth_one_factor
        )
        # 404, not 403: an unpublished course should not be discoverable at all.
        assert response.status_code == 404

    async def test_a_stepped_up_admin_does_see_drafts(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        lesson = await conn.fetchval("select id from lessons where slug = 'hidden'")
        response = await client.post(
            f"/api/lessons/{lesson}/playback", headers=admin_auth
        )
        assert response.status_code == 200


class TestCorsExposure:
    """A refusal the browser cannot read is a refusal the UI cannot act on.

    Only a handful of response headers are readable cross-origin by default and
    none of ours qualifies, so every custom header the frontend needs has to be
    named in Access-Control-Expose-Headers. This is worth a test because the
    failure is silent in the worst way: the header is present in curl and in the
    server log, and `response.headers.get(...)` in the browser returns null.
    """

    async def test_the_mfa_status_header_is_exposed(
        self, client: AsyncClient, conn, admin_auth_one_factor
    ) -> None:
        response = await client.get(
            ADMIN_ROUTE,
            headers={**admin_auth_one_factor, "Origin": "http://localhost:3000"},
        )
        assert response.status_code == 403
        exposed = {
            h.strip().lower()
            for h in response.headers.get("access-control-expose-headers", "").split(",")
        }
        assert "x-mfa-status" in exposed

    async def test_the_rate_limit_headers_are_exposed(
        self, client: AsyncClient, conn, admin_auth
    ) -> None:
        response = await client.get(
            ADMIN_ROUTE, headers={**admin_auth, "Origin": "http://localhost:3000"}
        )
        exposed = {
            h.strip().lower()
            for h in response.headers.get("access-control-expose-headers", "").split(",")
        }
        # Retry-After is the one that matters: without it a client that gets a
        # 429 has to guess how long to back off, which is how a limiter turns
        # into a retry storm.
        assert {"retry-after", "x-ratelimit-limit", "x-ratelimit-remaining"} <= exposed
