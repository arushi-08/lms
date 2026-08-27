#!/usr/bin/env python3
"""Probe a live Supabase project using ONLY its public anon key.

The anon key is designed to be public -- it ships in the browser. That is safe
only if row level security is on, because the key otherwise carries whatever
privileges Supabase granted to the `anon` role, which by default is full read
and write on every table you create.

This script asks the question that matters: standing where any visitor stands,
holding only the public key, what can I actually read and change?

    export SUPABASE_URL=https://<ref>.supabase.co
    export SUPABASE_ANON_KEY=<anon key>
    python3 scripts/verify_supabase.py

Read-only by default. Pass --probe-writes to additionally test whether the key
can insert (see _probe_write for why that test cannot create a row).

Exit codes: 0 all good, 1 something is exposed, 2 could not run the check.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

TIMEOUT = 20


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    fatal: bool = False
    #: What to do about it. A network failure and an unapplied schema are both
    #: fatal to the check but need opposite fixes, so the remedy travels with
    #: the result rather than being guessed at the call site.
    remedy: str = ""


class Probe:
    def __init__(self, url: str, key: str) -> None:
        self.url = url.rstrip("/")
        self.key = key

    def request(
        self, method: str, path: str, body: dict | None = None
    ) -> tuple[int, str]:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.url}/rest/v1/{path}", data=data, method=method
        )
        request.add_header("apikey", self.key)
        request.add_header("Authorization", f"Bearer {self.key}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
            request.add_header("Prefer", "return=minimal")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status, response.read().decode()[:400]
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()[:400]
        except (urllib.error.URLError, OSError, ValueError) as exc:
            # DNS, TLS, proxy refusal, timeout, malformed URL.
            return 0, f"{type(exc).__name__}: {exc}"


def _reachable(status: int) -> bool:
    """Did the public key actually get data back?"""
    return status == 200


def check_schema_present(probe: Probe) -> Result:
    """Positive control, and it must run first.

    Without this, every 'cannot read X' check below would pass trivially on a
    project where the schema was never applied -- a completely empty database
    would score a perfect report. That is the exact shape of a test suite that
    looks green and means nothing.
    """
    status, body = probe.request("GET", "courses?select=id&limit=1")
    if status == 0:
        return Result(
            "connectivity",
            False,
            body,
            fatal=True,
            remedy=(
                "Could not reach the project at all. Check the URL, your network, "
                "and that the project is not paused (free projects pause after ~7 "
                "days idle)."
            ),
        )
    if status in (404, 400) and "does not exist" in body or "PGRST205" in body:
        return Result(
            "schema applied",
            False,
            "table 'courses' is not exposed -- the migrations have not been applied",
            fatal=True,
            remedy="Apply supabase/migrations to the project, then run this again.",
        )
    if status in (401, 403):
        return Result(
            "schema applied",
            True,
            "courses exists and is locked down (no anon SELECT grant at all)",
        )
    if status == 200:
        return Result("schema applied", True, "courses is present and readable")
    return Result(
        "schema applied",
        False,
        f"unexpected HTTP {status}: {body}",
        fatal=True,
        remedy="Unexpected response; check the URL and the key are for the same project.",
    )


def confidentiality_checks(probe: Probe) -> list[Result]:
    """Things the public key must never be able to read."""
    secrets = [
        ("quiz_options", "quiz_options?select=*&limit=1", "the quiz answer key"),
        (
            "quiz_questions.correct_answers",
            "quiz_questions?select=correct_answers&limit=1",
            "short-text answer key",
        ),
        ("lessons.video_id", "lessons?select=video_id&limit=1", "video identifiers"),
        ("lessons.content", "lessons?select=content&limit=1", "paid lesson bodies"),
        ("payments", "payments?select=*&limit=1", "payment records"),
        ("provider_events", "provider_events?select=*&limit=1", "raw provider payloads"),
        ("audit_log", "audit_log?select=*&limit=1", "the audit trail"),
        (
            "video_playback_sessions",
            "video_playback_sessions?select=*&limit=1",
            "the playback ledger",
        ),
    ]
    results = []
    for name, path, what in secrets:
        status, _body = probe.request("GET", path)
        exposed = _reachable(status)
        results.append(
            Result(
                f"anon cannot read {name}",
                not exposed,
                f"EXPOSED -- {what} is world-readable" if exposed else f"blocked (HTTP {status})",
            )
        )
    return results


def isolation_checks(probe: Probe) -> list[Result]:
    results = []

    status, body = probe.request("GET", "profiles?select=id&limit=1")
    rows = json.loads(body) if status == 200 and body.strip().startswith("[") else None
    results.append(
        Result(
            "anon cannot list user profiles",
            not (status == 200 and rows),
            "EXPOSED -- student accounts are world-readable"
            if (status == 200 and rows)
            else f"no rows returned (HTTP {status})",
        )
    )

    status, body = probe.request("GET", "enrollments?select=id&limit=1")
    rows = json.loads(body) if status == 200 and body.strip().startswith("[") else None
    results.append(
        Result(
            "anon cannot list enrolments",
            not (status == 200 and rows),
            "EXPOSED -- who bought what is world-readable"
            if (status == 200 and rows)
            else f"no rows returned (HTTP {status})",
        )
    )

    status, body = probe.request("GET", "courses?select=slug,status")
    if status == 200 and body.strip().startswith("["):
        rows = json.loads(body)
        drafts = [r["slug"] for r in rows if r.get("status") != "published"]
        results.append(
            Result(
                "anon sees only published courses",
                not drafts,
                f"EXPOSED -- draft courses visible: {drafts}" if drafts else
                f"{len(rows)} published course(s), no drafts",
            )
        )
    else:
        results.append(
            Result("anon sees only published courses", True, f"catalog not readable (HTTP {status})")
        )

    return results


def _probe_write(probe: Probe) -> Result:
    """Test insert permission without creating a row.

    Posts an empty object to `courses`. That table has NOT NULL columns with no
    defaults (slug, title), so the request cannot succeed even where permission
    exists -- what differs is *which* error comes back:

        401/403  -> refused by privilege or policy. Good.
        400      -> allowed through to the not-null check. The key can write.
        201      -> a row was created. Something is very wrong with the schema.
    """
    status, _body = probe.request("POST", "courses", body={})
    if status in (401, 403):
        return Result("anon cannot write to courses", True, f"refused (HTTP {status})")
    if status == 400:
        return Result(
            "anon cannot write to courses",
            False,
            "EXPOSED -- insert reached column validation, so the public key can write",
        )
    if status == 201:
        return Result(
            "anon cannot write to courses",
            False,
            "EXPOSED -- a row was actually created by an unauthenticated request",
        )
    return Result("anon cannot write to courses", True, f"refused (HTTP {status})")


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    if not url or not key:
        print("set SUPABASE_URL and SUPABASE_ANON_KEY", file=sys.stderr)
        return 2

    probe = Probe(url, key)
    print(f"probing {url} with the public anon key\n")

    schema = check_schema_present(probe)
    results = [schema]

    if schema.fatal:
        _render(results)
        print(f"\nCannot assess security: {schema.detail}", file=sys.stderr)
        if schema.remedy:
            print(schema.remedy, file=sys.stderr)
        # Deliberately NOT exit 1: "I could not check" must never be reported
        # as "I checked and it is fine", nor as a confirmed exposure.
        return 2

    results += confidentiality_checks(probe)
    results += isolation_checks(probe)
    if "--probe-writes" in sys.argv:
        results.append(_probe_write(probe))

    _render(results)

    failures = [r for r in results if not r.ok]
    if failures:
        print(f"\n{len(failures)} problem(s) found. This project is not safe to put students on.")
        return 1
    print("\nAll checks passed. The public key cannot reach anything it should not.")
    return 0


def _render(results: list[Result]) -> None:
    width = max(len(r.name) for r in results)
    for r in results:
        mark = "ok  " if r.ok else "FAIL"
        print(f"  [{mark}] {r.name.ljust(width)}  {r.detail}")


if __name__ == "__main__":
    raise SystemExit(main())
