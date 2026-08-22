"""Database access.

One asyncpg pool, held on the app state. Queries live in ``app.repositories``
as explicit SQL rather than behind an ORM: the migrations are the schema's
source of truth, and an ORM model set would be a second definition to drift
from them.

The pool authenticates with the service role, which bypasses RLS. That is the
point -- this service is the component trusted to write enrolment and progress.
It also means every route is responsible for its own authorisation, and RLS is
the backstop rather than the gate. Anything reachable without an entitlement
check here is reachable by anyone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg

from app.config import Settings


class Database:
    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 5) -> None:
        self._dsn = dsn
        self._min = min_size
        self._max = max_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min,
                max_size=self._max,
                # Supabase's transaction pooler does not support prepared
                # statement caching; disabling it avoids "prepared statement
                # already exists" once more than one instance is running.
                statement_cache_size=0,
            )

    async def disconnect(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("database pool is not initialised")
        return self._pool

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        async with self.pool.acquire() as connection:
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[asyncpg.Connection]:
        async with self.pool.acquire() as connection, connection.transaction():
            yield connection


def build_database(settings: Settings) -> Database:
    return Database(
        settings.database_url.get_secret_value(),
        min_size=settings.database_pool_min,
        max_size=settings.database_pool_max,
    )
