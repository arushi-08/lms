# LMS Pilot — Build Scope & Free-Tier Stack

**Companion to `PLAN.md`.** That document is the target architecture. This one is what gets
built in the one-week pilot, on free tiers, and what is deliberately deferred.

**Revision:** r3 — incorporates the answers committed in `743dc9e` plus free-tier direction.

---

## 1. Answers absorbed

| # | Answer | Effect on the build |
|---|---|---|
| 3 | *(left at default)* | Quiz retries **unlimited**, no time limit. Schema keeps `max_attempts`/`time_limit_seconds` so a cap is a config change, not a migration. |
| 4 | Refunds revoke access **and** certificate | `certificates.revoked_at` is wired from the refund path, and the public verification page shows *"revoked"* rather than 404 — a revoked certificate that silently vanishes looks like a broken link, not a revocation. |
| 5 | **1 course, ~50 short videos** | Admin upload needs to be pleasant at 50 items: bulk upload queue, drag-reorder, inline rename. Not a one-at-a-time form. |
| 6 | **LMS is a separate project** | See §4 — needs a decision from you. |
| 7 | Stripe **not yet approved** | **Payments are out of the pilot.** See §3. |
| 8 | Students **both India and international** | Multi-currency and GDPR are real. Pilot stores `currency` per course and keeps PII deletion in scope; pricing UI deferred with payments. |
| 9 | Price TBD | Nothing blocked — no prices needed while payments are deferred. |
| 11 | Render | Backend on Render free tier. |
| 12 | **No VdoCipher account yet** | **Video provider is built behind an interface with a working mock.** See §2. |
| 13 | Brand assets exist | **I need them** — see §6. Building against a token layer meanwhile. |
| 14 | One week, budget ceiling, pilot first | Drives the cut list in §3. |

---

## 2. Two dependencies that aren't ready — and how the build routes around them

You have no VdoCipher account and no Stripe approval. Neither should stall a week of work, so
both sit behind an interface with a local implementation:

```python
class VideoProvider(Protocol):
    def create_upload(self, title: str) -> UploadTicket: ...
    def issue_playback(self, video_id: str, viewer: Viewer) -> PlaybackGrant: ...
    def get_status(self, video_id: str) -> VideoStatus: ...
```

- `MockVideoProvider` — serves a local sample file, fakes the OTP handshake and encoding
  delay, and **still runs the full enrolment/entitlement check** before granting playback.
  Selected by `VIDEO_PROVIDER=mock`. This means the access-control logic — the part that
  actually matters — is written, tested and reviewable now.
- `VdoCipherProvider` — real OTP + watermark + DRM. Selected by `VIDEO_PROVIDER=vdocipher`.
  Switching is one env var, no code change.

The same shape applies to payments (`PaymentProvider`), which is why an unapproved Stripe
account costs the pilot nothing.

**Testing plan:** 4–5 short sample videos, as you said. The mock provider covers the whole
flow end to end; when the VdoCipher account exists, those same 4–5 clips get uploaded for
real and the only thing that changes is one environment variable.

---

## 3. Pilot scope

### In
Auth and roles · course/module/lesson model · admin authoring with bulk video upload ·
DRM-gated playback (mock now, VdoCipher on switch) · progress tracking with server-side
clamping · quizzes with auto-grading · certificates with public verification · student
dashboard · design system · automated backups · CI.

### Out (deferred, not forgotten)
- **Payments.** Stripe isn't approved and the price isn't set. The pilot enrols students via
  free enrolment and admin grant. The `PaymentProvider` interface and the `payments` /
  `stripe_events` tables ship anyway, so Phase 5 is an adapter plus a webhook route.
- Notifications beyond Supabase's own auth emails (verify, reset). No Resend account needed
  for the pilot; the send interface is stubbed the same way.
- Coupons, drip scheduling, multi-currency pricing UI, i18n, in-app notification bell.

---

## 4. Where the code lives

Its own repository, `arushi-08/lms`, extracted from the `website` repo with
`git subtree split` so the commit history of every file came with it.

```
supabase/migrations/   schema + RLS, the source of truth
supabase/tests/        Supabase shim + adversarial RLS suite
apps/api/              FastAPI backend
apps/web/              Next.js frontend (not yet built)
.github/workflows/     CI, nightly backup, restore verification
```

Nothing here imports from the marketing site, and the copy under `website/lms` is retired.

---

## 5. Free-tier stack — and the one place it collides with your requirements

| Service | Free tier | Limit that will bite first | Upgrade trigger |
|---|---|---|---|
| **Supabase** | 500 MB DB, 1 GB storage, 5 GB egress, 50k MAU | **No backups**, and the project **pauses after ~7 days of inactivity** | Pro $25/mo at launch |
| **Render** | 512 MB web service | **Spins down after ~15 min idle**; cold start ~50 s | Starter $7/mo at launch |
| **Vercel** | Hobby | **ToS prohibits commercial use** — fine while nothing is for sale | Pro $20/mo the day you charge |
| **VdoCipher** | Trial only | No lasting free tier — hence the mock provider | Value $429/yr at launch |
| **Cloudflare R2** | 10 GB storage, no egress fees | Plenty for encrypted DB dumps | — |
| **GitHub Actions** | 2,000 min/mo | Plenty | — |
| **Sentry / PostHog / Upstash** | Free tiers | Plenty at pilot volume | — |

**Pilot running cost: $0.** Launch cost is the ~$90/mo "Lean" row in `PLAN.md` §4.3.

### The collision: free Supabase has no backups, but backups are non-negotiable

Your security list says *automated database backups from day one*, and the Supabase free tier
provides none. Rather than let that requirement lapse for the pilot, backups are
**self-managed from the first commit**:

- A **GitHub Actions cron** (nightly) runs `pg_dump` against the Supabase pooler.
- The dump is encrypted with **`age`** before it leaves the runner — the workflow never holds
  plaintext student data at rest.
- Encrypted dumps land in **Cloudflare R2** (free tier), 30-day retention.
- A **`restore-check` workflow** spins up a throwaway Postgres container, restores the latest
  dump into it and asserts the table count and a row count. An untested backup is a
  hypothesis, so the test runs on the same schedule as the backup.

This is strictly better than what Supabase Pro's daily backups give you on their own, and it
survives losing the Supabase account. When you move to Pro, its daily backups become the
second copy rather than the only one.

**Second free-tier hazard:** a Supabase project that idles for ~7 days is paused, which during
a part-time build week is a realistic way to lose an afternoon. The same nightly workflow
touches the database, which keeps it awake as a side effect.

---

## 6. What I need from you (not blocking — I'll keep building)

1. **Brand assets** — logo, colour values, font choices. The design system is being built as a
   token layer (`tokens.css`), so dropping your brand in is a values change, not a rebuild.
   Until they arrive I'm using a neutral, deliberately-chosen palette, *not* stock defaults.
2. **Supabase project** — create a free project and send me the URL and `anon` key. The
   `service_role` key goes straight into Render/GitHub secrets; don't paste it in chat.
3. **The 4–5 sample videos**, whenever convenient. The mock provider doesn't need them, but
   real files surface real problems (aspect ratios, durations, filenames).
4. Confirm the repo question in §4.

---

## 7. Build order for the week

| Day | Deliverable |
|---|---|
| 1 | Monorepo, schema + RLS migrations, CI, backup + restore-check workflows |
| 2 | FastAPI core: config, JWT verification, RBAC deps, provider interfaces, catalog API |
| 3 | Next.js app shell, design tokens, component primitives, auth flow |
| 4 | Admin authoring: course/module/lesson CRUD, bulk video upload, reordering |
| 5 | Player, entitlement-gated playback, progress heartbeats with server clamping |
| 6 | Quizzes, grading, certificates, verification page |
| 7 | Empty/error states, mobile pass at 360 px, a11y, E2E on the critical path |
