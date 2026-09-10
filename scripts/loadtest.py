#!/usr/bin/env python3
"""Measure API latency at the load 100 students actually generate.

The point of this script is that "will it stay under 200ms" stops being an
opinion. It separates three numbers that get conflated:

  floor     one request at a time — how fast the code is
  peak      the arrival rate 100 watching students really produce
  burst     everyone arriving in the same instant

Burst is the pessimistic case and the one that looks alarming; peak is the one
that matters. Run it against a staging deployment, not production.

    python3 scripts/loadtest.py --base http://localhost:8000 \
        --dsn "$DATABASE_URL" --course perf
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import UTC, datetime, timedelta

try:
    import asyncpg
    import httpx
    import jwt
except ImportError:
    raise SystemExit(
        "run from apps/api with its venv active:\n"
        "  cd apps/api && . .venv/bin/activate && python ../../scripts/loadtest.py ..."
    ) from None

SLO_MS = 200


def percentile(values: list[float], q: float) -> float:
    return values[min(int(len(values) * q), len(values) - 1)]


def report(name: str, samples: list[float], *, judge: bool = False) -> bool:
    samples.sort()
    p50, p95 = percentile(samples, 0.50), percentile(samples, 0.95)
    verdict = ""
    ok = True
    if judge:
        ok = p95 < SLO_MS
        verdict = "  <- within budget" if ok else f"  <- OVER the {SLO_MS}ms budget"
    print(
        f"  {name:<38} p50={p50:7.1f}ms  p95={p95:7.1f}ms  max={samples[-1]:7.1f}ms{verdict}"
    )
    return ok


async def run(base: str, dsn: str, slug: str, secret: str, issuer: str) -> int:
    conn = await asyncpg.connect(dsn)
    students = await conn.fetch(
        "select p.id, p.email from profiles p join enrollments e on e.user_id = p.id "
        "join courses c on c.id = e.course_id where c.slug = $1 limit 100",
        slug,
    )
    lessons = await conn.fetch(
        "select l.id from lessons l join modules m on m.id = l.module_id "
        "join courses c on c.id = m.course_id "
        "where c.slug = $1 and l.type = 'video' order by m.position, l.position",
        slug,
    )
    await conn.close()

    if not students or not lessons:
        print(f"no enrolled students or video lessons on course '{slug}'")
        return 2

    def token(user_id: str, email: str) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user_id),
                "email": email,
                "user_role": "student",
                "aud": "authenticated",
                "iss": issuer,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(hours=2)).timestamp()),
            },
            secret,
            algorithm="HS256",
        )

    tokens = [token(r["id"], r["email"]) for r in students]
    lesson_ids = [str(r["id"]) for r in lessons]
    print(f"{len(tokens)} students, {len(lesson_ids)} video lessons, target {base}")

    limits = httpx.Limits(max_connections=150, max_keepalive_connections=150)
    async with httpx.AsyncClient(timeout=30, limits=limits) as client:

        async def hit(i: int, path: str, body: dict | None = None, method: str = "POST") -> float:
            start = time.perf_counter()
            await client.request(
                method,
                base + path,
                headers={"Authorization": f"Bearer {tokens[i % len(tokens)]}"},
                json=body,
            )
            return (time.perf_counter() - start) * 1000

        # Warm the pool, the JWKS cache and query plans. Measuring a cold start
        # tells you about the first request, not about the service.
        for i in range(10):
            await hit(i, f"/api/lessons/{lesson_ids[0]}/progress",
                      {"watched_seconds": 5, "position_seconds": 5})

        print("\nFLOOR — one at a time, how fast the code is")
        for name, path, body, method in [
            ("liveness (no db, no auth)", "/healthz", None, "GET"),
            ("progress heartbeat", f"/api/lessons/{lesson_ids[1]}/progress",
             {"watched_seconds": 20, "position_seconds": 20}, "POST"),
            ("playback grant", f"/api/lessons/{lesson_ids[1]}/playback", None, "POST"),
        ]:
            samples = [await hit(i, path, body, method) for i in range(20)]
            report(name, samples)

        print("\nPEAK — 100 students watching, one heartbeat each per 10s (~10 rps)")
        samples: list[float] = []
        deadline = time.time() + 12
        cursor = 0
        while time.time() < deadline:
            batch = [
                hit(cursor + k, f"/api/lessons/{lesson_ids[(cursor + k) % len(lesson_ids)]}/progress",
                    {"watched_seconds": 30 + cursor, "position_seconds": 30 + cursor})
                for k in range(10)
            ]
            samples += await asyncio.gather(*batch)
            cursor += 10
            await asyncio.sleep(1.0)
        within = report(f"heartbeat, sustained (n={len(samples)})", samples, judge=True)

        print("\nBURST — all 100 in the same instant (pessimistic)")
        burst = list(await asyncio.gather(*[
            hit(i, f"/api/lessons/{lesson_ids[i % len(lesson_ids)]}/progress",
                {"watched_seconds": 90, "position_seconds": 90})
            for i in range(100)
        ]))
        report("heartbeat, 100 at once", burst)

    print()
    print("PASS — peak load is inside the budget" if within
          else "FAIL — peak load exceeds the budget")
    return 0 if within else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--dsn", required=True, help="DATABASE_URL")
    parser.add_argument("--course", default="perf", help="course slug to load against")
    parser.add_argument("--secret", default="integration-test-secret-at-least-32-bytes-long")
    parser.add_argument("--issuer", default="http://localhost:54321/auth/v1")
    args = parser.parse_args()
    return asyncio.run(run(args.base, args.dsn, args.course, args.secret, args.issuer))


if __name__ == "__main__":
    raise SystemExit(main())
