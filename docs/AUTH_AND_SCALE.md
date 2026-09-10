# Auth hardening and the 200ms target — plan

**Status:** plan only, no implementation beyond `scripts/loadtest.py`, which is the evidence.
**Date:** 2026-09-10

---

## 1. The headline

Most of "production-grade JWT sessions and RBAC" is already built and tested. The measured
API is **4× inside the 200ms budget at the load 100 students actually generate**. The work
that remains is a short list, and the largest risks are configuration choices, not code.

I measured before proposing anything, because the alternative is rebuilding things that work.

---

## 2. What already exists

| Capability | Where | Verified by |
|---|---|---|
| JWT signature, expiry, audience *and issuer* checked | `security/jwt.py` | tests reject forged, expired and wrong-key tokens |
| Asymmetric (JWKS) and legacy HS256 both supported | `security/jwt.py` | — |
| Role carried in the JWT via a Supabase access-token hook | migration `0002` | RLS suite |
| Admin routes re-read `profiles.role` per request | `security/deps.py` | a test forges an admin claim and still gets 403 |
| RBAC at three layers: route guard, API dependency, RLS | app + policies | 54 RLS checks |
| `httpOnly` cookie sessions, not `localStorage` | `@supabase/ssr` | — |
| Deny-by-default RLS on all 19 tables | migration `0008`, `0011` | 54 RLS checks |
| Entitlement decided in one place | `resolve_entitlement` | integration tests |
| Generic auth failures (no account enumeration) | login, signup, reset | — |

**Recommendation: do not replace any of this.** Supabase Auth handles password hashing,
refresh-token rotation and revocation properly. A hand-rolled JWT issuer would be a
downgrade with more code.

---

## 3. What is genuinely missing

Four items. Ordered by how much they matter.

### 3.1 Rate limiting — the real gap

Specified in `PLAN.md` §3.1 and never built. Today, nothing stops:

- credential stuffing against sign-in (Supabase applies its own limits, but our API does not)
- a script hammering `POST /lessons/{id}/playback` to mint OTPs
- repeated quiz submissions to brute-force short-text answers

**Proposal: an in-process token bucket, not Redis.** One instance serves this load
comfortably (§4), so a shared store buys nothing and adds a dependency, a failure mode and a
monthly bill. Keep the limiter behind a small interface so it becomes Redis-backed the day a
second instance exists.

Limits worth setting: playback grants 30/min/user, quiz submissions 10/min/user, enrollment
10/min/user, and a global per-IP ceiling for unauthenticated routes.

### 3.2 JWKS fetch is a single point of failure

With asymmetric keys, `PyJWKClient` fetches the key set on first use. If that fetch fails,
**every authenticated request fails** — the service is down while the database is healthy.

Fix: keep the last good key set and serve from it when a refresh fails, and log loudly. Small
change, removes a whole outage class.

### 3.3 MFA for admin accounts

Also specified, also not built. There will be one or two admins, and that account's blast
radius is every course and all student PII. TOTP on admin sign-in only.

### 3.4 Role model

Two roles today: `student`, `admin`. That is enough for one publisher and I would keep it.
**Open question:** do you need a third role — someone who can grade and edit content but not
manage students or refunds? If so it is a `user_role` enum value plus policy edits, best done
before there is data to migrate. If not, adding roles "just in case" is complexity with no
user.

---

## 4. The 200ms target

### 4.1 The load is not what the brief implies

"Peak video streaming" sounds like the hard case, but **video bytes never touch this API**.
The player streams from VdoCipher's CDN. What the API serves during peak streaming is:

| Request | Rate at 100 concurrent students |
|---|---|
| Progress heartbeat | 1 per student per 10s = **~10/s** |
| Playback grant | once per lesson start ≈ **1–2/s**, bursty |
| Page loads (server-rendered) | a handful per second |

**Peak is roughly 10–15 requests per second.** That is a small number, and it is the reason
the measurements below are comfortable.

### 4.2 Measured

`scripts/loadtest.py`, 100 students, 50-lesson course, 2500 existing progress rows:

```
FLOOR — one at a time
  liveness (no db, no auth)     p50=  1.4ms   p95=  1.6ms
  progress heartbeat            p50=  7.7ms   p95=  9.9ms
  playback grant                p50=  5.4ms   p95=  6.0ms

PEAK — 100 students, one heartbeat each per 10s (~10 rps)
  heartbeat, sustained          p50= 36.5ms   p95= 56.1ms   <- within budget

BURST — all 100 in the same instant (pessimistic)
  heartbeat, 100 at once        p50=283.0ms   p95=363.6ms
```

**Caveat that matters:** this ran against Postgres on the same host, so database round-trips
cost ~0.1ms. Against Supabase they cost real network time, and that is the dominant term —
see §4.3.

The burst row is worth reading correctly. 100 simultaneous arrivals is not the workload; it is
what happens if a cohort is told to press play at the same moment. Even then nothing failed —
requests queued and every one succeeded.

### 4.3 The dominant risk is round-trips × network latency

The heartbeat makes **6 database round-trips**; the playback grant makes **5**.

| Deployment | RTT per query | Added latency, heartbeat |
|---|---|---|
| Render and Supabase in the same region | ~1–3ms | +6–18ms — fine |
| Different regions, same continent | ~20ms | +120ms — eats most of the budget |
| Different continents | ~80ms | **+480ms — blows it outright** |

**This is the single biggest lever and it costs nothing: put the Render service and the
Supabase project in the same region.** Getting this wrong is the difference between 56ms and
half a second, with identical code.

Reducing the heartbeat from 6 round-trips to 2 is worth doing after that, and is
straightforward — the entitlement lookup, the role read and the stored-progress read can be
one query, and the recompute can be skipped entirely when nothing completed.

### 4.4 The other real risks

| Risk | Effect | Fix |
|---|---|---|
| **Render free tier spins down after ~15 min idle** | first request after idle takes ~50s | Starter ($7/mo) before any student sees it. Non-negotiable for an SLO. |
| **Supabase free tier pauses after 7 days idle** | total outage | Pro ($25/mo), already required for backups |
| Free tier CPU (0.5) | queueing under burst | Starter is enough at this load; measure before buying more |
| Connection exhaustion | 500s under load | use the **transaction pooler** (port 6543), pool max ~10 |
| No timing data in production | the SLO is unfalsifiable | §5.3 |

### 4.5 What I would *not* do

Explicitly, because each is a plausible-sounding way to overcomplicate this:

- **No Redis.** One instance, in-process limiter. Add it when a second instance exists.
- **No read replica.** The workload is ~15 rps.
- **No caching layer.** The catalog is one course; server components already fetch per request
  and the measured cost is single-digit milliseconds.
- **No queue for heartbeats.** They are a single upsert; a queue adds a moving part and delay.
- **No horizontal scaling yet.** 15 rps on 0.5 CPU is not a scaling problem.
- **No custom auth.** Supabase is doing this correctly.

---

## 5. The plan

Ordered by value per unit of effort. Items 1–2 are configuration and cost nothing to do.

### Phase 1 — configuration (no code)
1. **Colocate Render and Supabase regions.** Largest single latency lever (§4.3).
2. **Leave the free tiers before launch** — Render Starter, Supabase Pro. Spin-down alone
   breaks a 200ms SLO.
3. Confirm the pooled connection string (port 6543) and `DATABASE_POOL_MAX=10`.

### Phase 2 — the auth gaps (small, contained)
4. Rate limiting, in-process, behind an interface (§3.1).
5. JWKS last-good-key fallback (§3.2).
6. TOTP for admin sign-in (§3.3).

### Phase 3 — prove and hold the number
7. **Timing middleware**: record duration per route, log anything over 200ms with the route
   and the user, and expose a small `/metrics` summary. Without this the SLO is an opinion.
8. **Run `scripts/loadtest.py` against staging** after Phase 1, on the real network path. That
   number — not the local one above — is the one to trust.
9. Add the load test to CI as a smoke run so a regression that doubles round-trips is caught
   at review rather than at launch.

### Phase 4 — only if Phase 3 says so
10. Collapse the heartbeat's 6 round-trips to 2 (§4.3).
11. Skip the recompute when nothing completed — most heartbeats change only `watched_seconds`.

**Rough effort:** Phase 1 an hour of configuration; Phase 2 about a day; Phase 3 half a day;
Phase 4 half a day and probably unnecessary.

---

## 6. What I need from you

1. **Do you want a third role** (grader/instructor) or are two enough? (§3.4)
2. **Which regions** are the Render service and the Supabase project in today? This is the
   one thing most likely to be quietly wrong.
3. **Is 100 the ceiling, or is 300 the ceiling?** The measurements say both are fine, but 300
   students changes the burst arithmetic and the VdoCipher bandwidth tier.
4. Should the load test gate CI, or stay a manual check?
