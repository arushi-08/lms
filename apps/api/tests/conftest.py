"""Integration test fixtures.

These tests run against a real Postgres with the real migrations applied, using
the Supabase shim from ``lms/supabase/tests``. Mocking the database here would
defeat the purpose: most of what is being tested is whether the SQL, the
constraints and the entitlement checks agree with each other.

Tokens are genuine HS256 JWTs verified by the real verification path, so the
auth code is exercised rather than stubbed out.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import jwt
import pytest
from pydantic import SecretStr

from app.config import Settings


def _find_supabase_dir() -> Path:
    """Locate supabase/ by walking up, not by counting parent directories.

    A hardcoded parents[n] silently points at the wrong place the moment the
    tree is moved or extracted into its own repository, and the failure looks
    like a missing migration rather than a bad path.
    """
    for candidate in Path(__file__).resolve().parents:
        supabase = candidate / "supabase"
        if (supabase / "migrations").is_dir():
            return supabase
    raise RuntimeError("could not locate supabase/migrations above this file")


SUPABASE_DIR = _find_supabase_dir()

PG_HOST = os.environ.get("TEST_PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("TEST_PG_PORT", "5432")
PG_USER = os.environ.get("TEST_PG_USER", "postgres")
PG_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "pgtest")
PG_DB = os.environ.get("TEST_PG_DB", "lms_api_test")

JWT_SECRET = "integration-test-secret-at-least-32-bytes-long"
SUPABASE_URL = "http://localhost:54321"

ALICE = UUID("11111111-1111-1111-1111-111111111111")   # enrolled student
BOB = UUID("22222222-2222-2222-2222-222222222222")     # signed in, not enrolled
ADMIN = UUID("33333333-3333-3333-3333-333333333333")


def _dsn(database: str) -> str:
    return f"postgresql://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{database}"


def _psql(database: str, *, file: Path | None = None, sql: str | None = None) -> None:
    cmd = ["psql", "-v", "ON_ERROR_STOP=1", "-q", _dsn(database)]
    if file is not None:
        cmd += ["-f", str(file)]
    if sql is not None:
        cmd += ["-c", sql]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"psql failed:\n{result.stderr}")


def _postgres_available() -> bool:
    return (
        subprocess.run(
            ["pg_isready", "-h", PG_HOST, "-p", PG_PORT], capture_output=True
        ).returncode
        == 0
    )


def _require_postgres_or_skip() -> None:
    """Skip locally when there is no database; fail loudly in CI.

    Skipping is right on a laptop with no Postgres running. It is wrong in CI,
    where a misconfigured service container would quietly drop every integration
    test and leave a green tick over untested code. REQUIRE_INTEGRATION_TESTS
    turns the skip into a failure.
    """
    if _postgres_available():
        return
    message = f"no Postgres reachable at {PG_HOST}:{PG_PORT}"
    if os.environ.get("REQUIRE_INTEGRATION_TESTS") == "1":
        raise RuntimeError(f"{message} and REQUIRE_INTEGRATION_TESTS=1")
    pytest.skip(message, allow_module_level=True)


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    _require_postgres_or_skip()

    _psql("postgres", sql=f'drop database if exists "{PG_DB}"')
    _psql("postgres", sql=f'create database "{PG_DB}"')

    _psql(PG_DB, file=SUPABASE_DIR / "tests" / "00_shim_supabase.sql")
    for migration in sorted((SUPABASE_DIR / "migrations").glob("*.sql")):
        _psql(PG_DB, file=migration)

    # Users, an enrolment for Alice, a draft course, and playable videos.
    _psql(
        PG_DB,
        sql=f"""
        insert into auth.users (id, email, raw_user_meta_data) values
          ('{ALICE}', 'alice@example.test', '{{"full_name":"Alice"}}'),
          ('{BOB}',   'bob@example.test',   '{{"full_name":"Bob"}}'),
          ('{ADMIN}', 'admin@example.test', '{{"full_name":"Admin"}}');
        update profiles set role = 'admin' where id = '{ADMIN}';
        insert into enrollments (user_id, course_id, source)
          select '{ALICE}', id, 'free' from courses where slug = 'pilot-course';
        insert into courses (slug, title, status, access_type, is_free, currency)
          values ('draft-course', 'Draft', 'draft', 'lifetime', true, 'USD');
        insert into modules (course_id, title, position)
          select id, 'Hidden', 1 from courses where slug = 'draft-course';
        insert into lessons (module_id, title, slug, type, position, video_id, video_status,
                             duration_seconds)
          select m.id, 'Hidden Lesson', 'hidden', 'video', 1, 'vid-hidden', 'ready', 600
          from modules m join courses c on c.id = m.course_id where c.slug = 'draft-course';
        update lessons set video_id = 'vid-' || slug, video_status = 'ready',
                           duration_seconds = 600
          where type = 'video';
        """,
    )
    yield _dsn(PG_DB)


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(
        environment="development",
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=SecretStr(JWT_SECRET),
        supabase_service_role_key=SecretStr("test-service-role"),
        database_url=SecretStr(database_url),
        video_provider="mock",
        cors_origins=["http://localhost:3000"],
    )


def token_for(user_id: UUID, email: str, role: str = "student", *, expired: bool = False) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(user_id),
            "email": email,
            "user_role": role,
            "aud": "authenticated",
            "iss": f"{SUPABASE_URL}/auth/v1",
            "iat": int(now.timestamp()),
            "exp": int(
                (now - timedelta(hours=1) if expired else now + timedelta(hours=1)).timestamp()
            ),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


@pytest.fixture
def alice_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(ALICE, 'alice@example.test')}"}


@pytest.fixture
def bob_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(BOB, 'bob@example.test')}"}


@pytest.fixture
def admin_auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {token_for(ADMIN, 'admin@example.test', 'admin')}"}
