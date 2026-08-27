# LMS Platform — Technical Plan

**Status:** Plan only. No code written. Awaiting go-ahead.
**Revision:** r2 — four decisions confirmed, see §0.1.
**Target scale:** 300 students (single publisher / personal course-sharing).
**Date:** 2026-08-22

## Contents
1. [Architecture & key components](#1-architecture--key-components)
2. [Database schema outline](#2-database-schema-outline)
3. [Security requirements checklist](#3-security-requirements-checklist)
4. [Paid third-party services & cost](#4-paid-third-party-services--cost)
5. [Assumptions & open questions](#5-assumptions--open-questions)
6. [Build sequence](#6-build-sequence)

---

## 0. Fixed stack (per brief)

| Layer | Choice |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Frontend | React + TypeScript — **Next.js App Router** (confirmed) |
| Auth + DB | Supabase (Postgres + GoTrue Auth + Storage + RLS) |
| Video | VdoCipher (DRM, no downloads) |
| Hosting | Vercel (frontend), Render **or** Railway (backend) |
| Payments | Stripe (free + paid courses) — behind a provider interface, see §1.G-IN |

## 0.1 Decisions confirmed (2026-08-22)

| # | Decision | Consequence |
|---|---|---|
| 1 | **Access model is per-course.** First course: one-time purchase, lifetime access. Other courses may differ later. | Access policy moves onto the `courses` row (`access_type` + `access_days`) and is resolved into `enrollments.expires_at` at enrolment time. §2.2, §2.3. |
| 2 | **Selling entity is registered in India.** | Payment layer goes behind a provider interface; Stripe stays the target but is no longer assumed. GST enters scope. See §1.G-IN — **this is the one open commercial risk in the plan**. |
| 3 | **Frontend is Next.js (App Router).** | Server-rendered catalog for SEO; `@supabase/ssr` cookie sessions instead of `localStorage`. |
| 4 | **Certificate = all required lessons complete + all quizzes passed. No gating.** | A failed quiz does not lock the next lesson. Unlimited retries by default (`max_attempts` null). §1.E, §1.F. |

---

## 1. Architecture & key components

### 1.1 The critical design question: who owns what, Supabase or FastAPI?

Having both Supabase and FastAPI means there are two possible paths to the database. Getting
this boundary wrong is the main way this architecture goes bad. The rule:

> **Supabase is the system of record and the identity provider. FastAPI is the only writer
> for anything that has money, grades, or access rights attached to it.**

| Path | Used for | Key used |
|---|---|---|
| Browser → Supabase (direct) | Reads of published catalog, own profile, own progress, own certificates. Protected by RLS. | `anon` key (public by design — safe **only** because RLS is on) |
| Browser → FastAPI → Supabase | Enrolment, payments, quiz submission & grading, certificate issuance, video OTP, all admin writes | `service_role` key (**server-only, never shipped to the browser**) |

Anything a student could benefit from lying about goes through FastAPI. Quiz answer keys, for
instance, must never be reachable by the `anon` key at all — not hidden in the UI, *denied by
RLS*.

### 1.2 Component map

```
┌──────────────────────── Vercel ────────────────────────┐
│  Next.js (React + TS)                                  │
│  ├── /            marketing + course catalog (SSR/SEO) │
│  ├── /learn/*     player, quizzes, progress            │
│  ├── /dashboard   enrolled courses, certificates       │
│  └── /admin/*     course authoring (role-gated)        │
└────────┬──────────────────────────┬────────────────────┘
         │ anon key + RLS           │ HTTPS + Bearer JWT
         │ (reads only)             │
         ▼                          ▼
┌──── Supabase ────┐      ┌──── Render/Railway ─────────┐
│ Postgres + RLS   │◄─────┤  FastAPI (service_role key) │
│ Auth (GoTrue)    │      │  ├── /auth/me               │
│ Storage (certs)  │      │  ├── /enrollments           │
└──────────────────┘      │  ├── /video/otp   ─────────►│──► VdoCipher API
         ▲                │  ├── /quiz/submit           │
         │ nightly pg_dump│  ├── /certificates          │
         │                │  ├── /admin/*               │
┌── Cloudflare R2 ─┐      │  └── /webhooks/stripe ◄─────│──── Stripe
│ offsite backups  │      └─────────────────────────────┘
└──────────────────┘
```

### 1.3 Components in detail

#### A. Authentication & identity
- **Supabase Auth (GoTrue)** — email+password (bcrypt, handled by Supabase), email
  verification required, magic-link and Google OAuth optional.
- FastAPI verifies the Supabase JWT on every request using the project's **JWKS endpoint**
  (`/auth/v1/.well-known/jwks.json`) with asymmetric keys, cached in-process. A FastAPI
  dependency (`get_current_user`) resolves `sub` → `profiles` row and attaches the role.
- **Role** lives in `profiles.role` (`student` | `admin`) and is mirrored into the JWT via a
  Supabase **Custom Access Token Hook**, so RLS policies can read it without a table join.
  Roles are only ever set by the `service_role` key or by SQL — never from a client payload.

#### B. Course content & catalog
- Hierarchy: **Course → Module → Lesson**. Lesson types: `video`, `text`, `quiz`.
- Explicit integer `position` on modules and lessons for ordering (drag-and-drop in admin).
- `status` (`draft`/`published`/`archived`) so you can build a course before it goes live.
- Rich text for `text` lessons authored with **TipTap**, stored as JSON, sanitised
  **server-side** with `nh3`/`bleach` before storage — never trust the editor's output.
- `is_preview` flag lets a lesson play without enrolment (a real conversion driver).

#### C. Video delivery (VdoCipher, DRM)
This is the part with the hard security requirement, so the flow is worth spelling out.

**Upload (admin):** FastAPI calls VdoCipher for upload credentials → browser uploads the file
directly to VdoCipher (never through our backend) → FastAPI polls until the video is ready →
stores `vdocipher_video_id` on the lesson.

**Playback (student):**
1. Browser asks `POST /api/video/otp` with the lesson id and its JWT.
2. FastAPI checks: is the user authenticated, enrolled in the parent course, is the enrolment
   active (not refunded/expired), is the lesson published or a preview?
3. Only then does FastAPI call VdoCipher `POST /api/videos/{id}/otp` with the **API secret**
   (server-only), requesting a short TTL (**300 s**) and a dynamic watermark annotation
   carrying the student's email, user id and timestamp.
4. FastAPI returns `{otp, playbackInfo}` to the browser, which hands them to the VdoCipher
   player iframe. **No video URL ever exists in our code, our database, or the page source.**
5. The OTP request is logged to `video_playback_sessions` for audit and concurrency limits.

**Enforcing "no downloads":** DRM (Widevine / FairPlay / PlayReady) is enabled at the
VdoCipher account level; offline download is switched **off** in account settings; the player
domain allowlist is restricted to our production and preview domains. One honest caveat:
DRM blocks screen recording on most platforms but not every browser/OS combination, and no
system stops a camera pointed at a screen. The dynamic watermark is what makes a leak
traceable back to the student who leaked it — that is the real deterrent, and it is why I
want it on from day one rather than as a later add-on.

#### D. Progress tracking
- The VdoCipher player's JS API emits time updates. The client batches these and sends a
  **heartbeat every ~20 s** to `POST /api/progress` with `watched_seconds` and
  `last_position_seconds`.
- Server-side anti-cheat: the reported watched-time delta is **clamped to wall-clock elapsed
  time** since that user's previous heartbeat. You cannot POST your way to a certificate.
- A lesson completes at **≥90 %** watched (configurable per course) or via an explicit
  "mark complete" for text lessons.
- `enrollments.progress_percent` is a **maintained column**, recalculated on each completion
  rather than aggregated on read — keeps the dashboard a single fast query.
- Resume-where-you-left-off comes free from `last_position_seconds`.

#### E. Quizzes & auto-grading
- Question types v1: single-choice, multi-select, true/false, short text (normalised exact
  match). Per-question `points` and optional `explanation` shown after submission.
- **Grading is 100 % server-side in FastAPI.** The student-facing question endpoint returns
  options *without* `is_correct`; RLS additionally denies the `anon` key any access to
  `quiz_options.is_correct`. Two independent layers, because this is the one place where a
  leak silently invalidates every certificate you have ever issued.
- Attempt tracking with `max_attempts` (**default null = unlimited retries**, per decision 4),
  optional server-enforced time limit, optional question shuffling, pass/fail against
  `passing_score`.
- **No progression gating**: failing a quiz does not lock the next lesson. It only withholds
  the certificate until passed.

#### F. Certificates
- **Completion rule (confirmed):** every lesson with `is_required = true` is complete **and**
  every quiz in the course has at least one passing attempt. Evaluated server-side after each
  lesson completion and each quiz submission.
- PDF generated server-side with **WeasyPrint** from an HTML template (so the certificate is
  styled with the same design tokens as the site), stored in a **private** Supabase Storage
  bucket, delivered via a short-lived signed URL.
- Each certificate gets a UUID serial and a **public verification page**
  (`/verify/{serial}`) showing student name, course, issue date — with a QR code on the PDF
  pointing at it. Idempotent: one certificate per (user, course), re-download never re-issues.

#### G. Payments (Stripe)
- **Stripe Checkout** (hosted) rather than a custom card form. This keeps you in PCI **SAQ-A**
  — the lightest compliance burden — because no card data ever touches your servers.
- Flow: FastAPI creates a Checkout Session with the price **read from the database, never from
  the client**, plus `client_reference_id = user_id` and `metadata.course_id`.
- **Webhook `checkout.session.completed`** → verify the Stripe signature → idempotency check
  against a `stripe_events` table → create `enrollment` + `payment` rows in one transaction.
  Enrolment is granted by the webhook, **not** by the browser redirect (which users can fake
  or simply never reach).
- Also handled: `charge.refunded` → set enrolment `refunded`, revoke access;
  `charge.dispute.created` → alert.
- Free courses skip the payment provider entirely via a separate enrol endpoint.

#### G-IN. India: the payment provider is now a real risk, not a detail

You confirmed the selling entity is registered in India. The brief fixes Stripe, and I am
still planning against Stripe — but I am not going to quietly build on an assumption that
could fail at launch, so here is the concern stated once, with the mitigation baked in.

**The concern.** Stripe operates in India, but onboarding for Indian-registered entities has
been restricted/invite-only for extended stretches, and Indian payment rules (RBI card
tokenisation, and the e-mandate/additional-factor rules that make card-on-file recurring
billing awkward) constrain what a Stripe integration can do domestically. Separately,
selling to overseas customers from India brings export-of-services paperwork.

**The mitigation — build it provider-agnostic from the start.** This costs roughly half a
day now and saves a rewrite later:

```python
class PaymentProvider(Protocol):
    def create_checkout(self, user, course) -> CheckoutRedirect: ...
    def verify_webhook(self, body: bytes, sig: str) -> ProviderEvent: ...
```

Everything downstream — enrolment, `payments`, refunds, the dashboard — consumes a
**normalised** `PaymentSucceeded(user_id, course_id, amount_cents, currency, provider_ref)`
event and never imports the Stripe SDK. Swapping to Razorpay then means writing one adapter
class, not touching enrolment logic.

**The options, so you can decide with numbers:**

| Option | Fees (approx) | Fits |
|---|---|---|
| **Stripe** (as briefed) | 2.9% + $0.30 intl / ~2% + ₹3 domestic | If your account is approved. Best DX, matches the brief. |
| **Razorpay / Cashfree** | ~2% + GST domestic | The standard route for Indian entities selling to Indian customers. UPI, netbanking, cards. |
| **Merchant of Record** (Paddle, Lemon Squeezy) | ~5% + $0.50 | They become the legal seller: they handle global VAT/GST registration and remit to an Indian bank. Higher fee, far less tax admin — genuinely worth considering for a solo seller with international students. |

**Action for you, before Phase 5:** confirm Stripe will actually onboard your entity. If it
will, nothing in this plan changes. If it won't, we drop in a Razorpay adapter and the rest
of the build is unaffected.

**Also in scope now that it's India:** GST on digital course sales (18% is the standard rate
for this category) and the registration thresholds that apply to you. I'll build price
handling so tax is a separate, configurable component on the `courses` row rather than baked
into `price_cents` — but the actual GST position is a question for your CA, not for me.

#### H. Admin panel (no code changes to add content)
A custom `/admin` area in the same React app, role-gated at the route, the API and the RLS
layer. Off-the-shelf tools (Supabase Studio, Retool) were considered and rejected: Studio is
a raw table editor, not something you want to author a course in, and Retool bills per user
and would not match the design system.

Covers: course CRUD with draft/publish; drag-and-drop module & lesson ordering; direct video
upload with progress and encoding status; TipTap rich-text lessons; a quiz builder; student
list with progress; manual enrolment grant/revoke; payment & refund history; certificate
re-issue. Every admin mutation writes to `audit_log`.

#### I. Notifications
- **Transactional email via Resend** with React Email templates. Supabase's built-in SMTP is
  rate-limited and explicitly not for production, so custom SMTP is configured on day one.
- Emails: verify address, password reset, enrolment confirmation, course completion +
  certificate, quiz passed, new lesson published, 14-day inactivity nudge.
- In-app notification bell backed by a `notifications` table (Supabase Realtime optional).

#### J. Design system (the "polished" bar)
Not a default component library skin. Concretely:
- A **token layer** in CSS custom properties — colour ramps, a modular type scale, a 4 px
  spacing scale, radii, shadows, motion durations — consumed by a custom Tailwind theme.
- **Radix UI primitives** (unstyled, accessible) styled from those tokens. shadcn/ui may be
  used as a starting point but is restyled; the goal is that it does not look like shadcn.
- Deliberate typography: one display face for headings, one text face, with real line-height
  and measure discipline.
- Mobile-first, verified down to a 360 px viewport; the video player and quiz UI get explicit
  mobile layouts rather than being squeezed.
- WCAG 2.2 AA: keyboard navigation throughout, visible focus rings, labelled controls,
  captions on video (VdoCipher supports subtitle tracks).
- **Every empty and error state designed, not defaulted**: no courses yet, no enrolments, no
  certificates, course with no modules, quiz with no questions, video failed to load, OTP
  expired (auto-retry once), payment pending, offline. This is a named QA checklist item, not
  a nice-to-have — it is the difference between "polished" and "demo".

#### K. Repository & environments
- Monorepo: `apps/web` (Next.js), `apps/api` (FastAPI), `supabase/migrations` (SQL, versioned
  via Supabase CLI — **the schema is code, never clicked into the dashboard**).
- TypeScript API types generated from FastAPI's OpenAPI schema (`openapi-typescript`), so a
  backend field rename breaks the frontend build instead of production.
- Separate **dev and prod Supabase projects**. Vercel preview deploys per PR.
- CI (GitHub Actions): ruff + mypy + pytest, eslint + tsc + vitest, `pip-audit`, `npm audit`,
  gitleaks secret scan, Playwright E2E on the critical path
  (sign up → buy → watch → quiz → certificate).

---

## 2. Database schema outline

Postgres on Supabase. `auth.users` is Supabase-managed; everything below is in `public`.
All tables have `created_at timestamptz default now()`; mutable tables have `updated_at`
maintained by a trigger. **RLS is enabled on every single table, with deny-by-default.**

### 2.1 Identity

**`profiles`** — 1:1 with `auth.users`, created by a trigger on signup.
| column | type | notes |
|---|---|---|
| `id` | `uuid` PK | FK → `auth.users.id` on delete cascade |
| `email` | `text` | mirrored for admin search |
| `full_name` | `text` | printed on certificates |
| `avatar_url` | `text` null | |
| `role` | `user_role` enum | `student` \| `admin`, default `student` |

### 2.2 Content

**`courses`**
| column | type | notes |
|---|---|---|
| `id` | `uuid` PK | |
| `slug` | `text` unique | SEO URL |
| `title`, `subtitle`, `description` | `text` | |
| `thumbnail_url` | `text` | Supabase Storage, public bucket |
| `is_free` | `bool` | |
| `price_cents` | `int` | 0 when free |
| `currency` | `char(3)` | |
| `stripe_price_id` | `text` null | |
| `status` | `content_status` enum | `draft` \| `published` \| `archived` |
| `completion_threshold` | `int` | % of a video counted as watched, default 90 |
| `access_type` | `access_type` enum | `lifetime` \| `time_limited`, default `lifetime` — **per course** |
| `access_days` | `int` null | required when `access_type='time_limited'` |
| `tax_rate_bps` | `int` | tax added at checkout, in basis points (1800 = 18% GST). Kept out of `price_cents`. |
| `published_at` | `timestamptz` null | |

**`modules`** — `id`, `course_id` FK cascade, `title`, `description`, `position int`.
Unique `(course_id, position)` deferrable.

**`lessons`**
| column | type | notes |
|---|---|---|
| `id` | `uuid` PK | |
| `module_id` | `uuid` FK cascade | |
| `title`, `slug` | `text` | |
| `type` | `lesson_type` enum | `video` \| `text` \| `quiz` |
| `position` | `int` | unique per module |
| `is_preview` | `bool` | playable without enrolment |
| `is_required` | `bool` | counts toward completion |
| `duration_seconds` | `int` null | |
| `content` | `jsonb` null | TipTap doc for `text` lessons |
| `vdocipher_video_id` | `text` null | for `video` lessons |
| `vdocipher_status` | `text` null | `uploading`/`processing`/`ready` |

### 2.3 Enrolment & progress

**`enrollments`** — unique `(user_id, course_id)`
| column | type | notes |
|---|---|---|
| `id` | `uuid` PK | |
| `user_id` | `uuid` FK → profiles | |
| `course_id` | `uuid` FK → courses | |
| `status` | `enrollment_status` enum | `active` \| `refunded` \| `expired` |
| `source` | `enrollment_source` enum | `purchase` \| `free` \| `manual` |
| `progress_percent` | `numeric(5,2)` | maintained, not computed on read |
| `last_lesson_id` | `uuid` null | "resume course" |
| `expires_at` | `timestamptz` null | resolved **at enrolment time** from the course's `access_type`/`access_days`; null = lifetime. Snapshotting it here means changing a course's policy later never retroactively revokes access someone already paid for. |
| `enrolled_at`, `completed_at` | `timestamptz` | |

Index: `(user_id, status)`, `(course_id)`.

**`lesson_progress`** — unique `(user_id, lesson_id)`
`id`, `user_id`, `lesson_id`, `enrollment_id`, `watched_seconds int`,
`last_position_seconds int`, `completed bool`, `completed_at`, `updated_at`.
Index: `(user_id, lesson_id)`, `(enrollment_id) where completed`.

### 2.4 Assessment

**`quizzes`** — `id`, `lesson_id` FK unique, `title`, `passing_score int`,
`max_attempts int` null, `time_limit_seconds int` null, `shuffle_questions bool`.

**`quiz_questions`** — `id`, `quiz_id` FK cascade, `type` enum
(`single`\|`multi`\|`boolean`\|`short_text`), `prompt text`, `explanation text` null,
`points int` default 1, `position int`.

**`quiz_options`** — `id`, `question_id` FK cascade, `text`, **`is_correct bool`**,
`position int`.
> This table is the crown jewel. RLS grants `SELECT` to `service_role` **only**. Student
> question payloads are assembled in FastAPI with `is_correct` stripped. For `short_text`
> questions the accepted answers live in `quiz_questions.correct_answers text[]`, under the
> same restriction.

**`quiz_attempts`** — `id`, `quiz_id`, `user_id`, `attempt_number int`, `started_at`,
`submitted_at` null, `score numeric`, `passed bool`, `time_spent_seconds`.
Unique `(quiz_id, user_id, attempt_number)`.

**`quiz_responses`** — `id`, `attempt_id` FK cascade, `question_id`,
`selected_option_ids uuid[]`, `text_answer text` null, `is_correct bool`,
`points_awarded numeric`.

### 2.5 Certificates

**`certificates`** — unique `(user_id, course_id)`
`id uuid` PK, `serial text` unique (the public verification code), `user_id`, `course_id`,
`student_name_snapshot text` (name as printed — must not change if the profile is edited),
`course_title_snapshot text`, `issued_at`, `pdf_path text`, `revoked_at` null.

### 2.6 Money

**`payments`** — `id`, `user_id`, `course_id`, `stripe_checkout_session_id` unique,
`stripe_payment_intent_id`, `amount_cents`, `currency`, `status` enum
(`pending`\|`paid`\|`refunded`\|`disputed`), `refunded_at` null.

**`stripe_events`** — `id text` PK (the Stripe event id), `type`, `payload jsonb`,
`processed_at`. Inserting the id **is** the idempotency lock; a duplicate webhook delivery
hits the primary-key conflict and exits cleanly.

### 2.7 Operational

**`video_playback_sessions`** — `id`, `user_id`, `lesson_id`, `issued_at`, `ip inet`,
`user_agent text`. Feeds concurrency limits and leak investigation.

**`audit_log`** — `id`, `actor_id`, `action text`, `entity_type`, `entity_id`, `diff jsonb`,
`ip inet`, `created_at`. Insert-only; no update/delete grant to anyone.

**`notifications`** — `id`, `user_id`, `type`, `title`, `body`, `read_at` null.

### 2.8 RLS policy sketch

| Table | student | admin |
|---|---|---|
| `courses`, `modules`, `lessons` | `SELECT` where `status='published'` (and lesson body only if enrolled or `is_preview`) | full |
| `enrollments`, `lesson_progress`, `quiz_attempts`, `quiz_responses`, `certificates`, `notifications` | `SELECT` where `user_id = auth.uid()`; **no direct INSERT/UPDATE** | full |
| `quiz_options`, `quiz_questions.correct_answers` | **no access** | full |
| `payments`, `stripe_events`, `audit_log`, `video_playback_sessions` | **no access** | `SELECT` |

Writes to the student-owned tables land through FastAPI with `service_role`, which bypasses
RLS — so RLS is the *second* line of defence, and the endpoint's own ownership check is the
first. Both are required.

---

## 3. Security requirements checklist

Your non-negotiables are marked **[brief]**. The rest are additions I consider necessary to
hold the same bar; none are optional in my view, but the ones marked *(later)* can follow v1.

### 3.1 Authentication
- [ ] **[brief]** Password hashing — handled by Supabase Auth (bcrypt). We never write our own.
- [ ] **[brief]** Rate-limited login — Supabase Auth's built-in per-IP auth limits, tuned;
      plus **Cloudflare Turnstile** captcha on signup and after N failed logins (natively
      supported by Supabase Auth).
- [ ] Application-level rate limiting on FastAPI (`slowapi` + Upstash Redis) for
      `/video/otp`, `/quiz/submit`, `/checkout` — per-user, not just per-IP.
- [ ] Email verification required before enrolment.
- [ ] Minimum password length 10 + Supabase's breached-password check (HIBP) enabled.
- [ ] Short access-token TTL (1 h) with refresh-token rotation; logout revokes the refresh token.
- [ ] Session stored in `httpOnly`, `Secure`, `SameSite=Lax` cookies via `@supabase/ssr` —
      **not** `localStorage`, which any XSS can read.
- [ ] TOTP MFA required for **admin** accounts. *(There will be one or two admins; the blast
      radius of that account is the entire platform and all student PII.)*
- [ ] Generic error messages on login/reset to prevent account enumeration.

### 3.2 Authorization
- [ ] **[brief]** Role-based access: `student` vs `admin`, enforced at three layers — route
      guard (UX), FastAPI dependency (the real gate), RLS policy (defence in depth).
- [ ] Role is server-owned: set only via `service_role`/SQL, propagated into the JWT by a
      custom access-token hook. A client-supplied role field is ignored everywhere.
- [ ] Deny-by-default RLS enabled on **every** table.
- [ ] Every object-scoped endpoint re-checks ownership/enrolment server-side (IDOR defence) —
      a valid JWT for user A must never read user B's attempt, progress or certificate.
- [ ] `service_role` key exists only in backend env vars. A CI check greps the frontend bundle
      for it.

### 3.3 Video access control
- [ ] **[brief]** Signed/expiring access, never public links: VdoCipher OTP with **300 s TTL**,
      minted per playback request.
- [ ] **[brief]** OTP issued only after an enrolment + status + expiry check passes.
- [ ] VdoCipher API secret is server-side only; the browser never sees a video URL or the
      video id in any pre-enrolment payload.
- [ ] DRM enabled (Widevine / FairPlay / PlayReady); **offline download disabled** in account
      settings.
- [ ] Player domain allowlist restricted to production + preview domains.
- [ ] Dynamic watermark burned into playback: student email + user id + timestamp.
- [ ] Concurrent-playback cap per user (e.g. 2 sessions) via `video_playback_sessions`, to
      catch shared accounts.
- [ ] OTP issuance logged with IP and user agent for leak tracing.

### 3.4 Payment handling
- [ ] **[brief]** Stripe Checkout only — no card data on our servers (PCI **SAQ-A**).
- [ ] Price and course id read from the database server-side; client-supplied amounts rejected.
- [ ] Webhook signature verified with the endpoint secret on every delivery.
- [ ] Idempotency via `stripe_events` primary key — replayed webhooks are no-ops.
- [ ] Access granted by the **webhook**, never by the success-redirect.
- [ ] Refund and dispute webhooks revoke enrolment.
- [ ] Payment mutations wrapped in a single DB transaction.

### 3.5 Data protection
- [ ] **[brief]** HTTPS everywhere — HSTS with preload; Vercel and Render/Railway terminate TLS;
      HTTP redirects to HTTPS.
- [ ] **[brief]** All secrets in environment variables. `.env.example` committed, `.env` never.
      **gitleaks** in CI. Documented rotation procedure.
- [ ] **[brief]** Automated backups from day one:
      - Supabase Pro daily backups, 7-day retention (this is *why* Pro is required, not Free);
      - **plus** a nightly `pg_dump` cron job to Cloudflare R2, encrypted with `age`, 30-day
        retention — because a provider-side backup is not a backup if you lose the account;
      - **a restore drill in month one and quarterly after**, documented. An untested backup
        is a hypothesis.
- [ ] Security headers: strict CSP (`frame-src` allowlisting VdoCipher's player and Stripe),
      `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`.
- [ ] CORS allowlist pinned to exact frontend origins. No wildcard.
- [ ] Pydantic v2 validation on every request body; response models to prevent field leakage.
- [ ] Server-side HTML sanitisation (`nh3`) on all rich text before storage and on render.
- [ ] Upload validation: content-type sniffing, size caps, filename normalisation.
- [ ] Separate dev and prod Supabase projects; **no production data in development**.
- [ ] Sentry on both ends with PII scrubbing; structured logs with no secrets or tokens.
- [ ] Dependabot/Renovate + `pip-audit` + `npm audit` in CI.
- [ ] Privacy policy, terms, cookie notice; data export and account-deletion endpoints
      (GDPR/DPDP) — scope depends on where your students are (open question).
- [ ] *(later)* Supabase PITR add-on if the 7-day daily-backup granularity stops being enough.

---

## 4. Paid third-party services & cost

All figures are **approximate list prices at time of writing (Aug 2026)** and should be
re-checked before you commit — SaaS pricing moves.

### 4.1 The one that actually matters: VdoCipher bandwidth

VdoCipher sells **annual prepaid credit**, not a monthly subscription: the plan ends when the
bandwidth is consumed *or* after 12 months, whichever comes first. So the plan has to be
sized against real viewing, and this is the single largest and most variable line item.

**Sizing formula:**
```
bandwidth (GB) = students × hours watched each × GB per hour
GB per hour ≈ 0.5 (480p) | 1.0–1.4 (720p) | 2.0–3.0 (1080p)
```

For 300 students at 720p:

| Hours watched per student | Bandwidth | Cheapest fitting plan |
|---|---|---|
| 5 h | ~1.8 TB | **Express** $699/yr (3 TB) |
| 10 h | ~3.6 TB | **PRO** $1,549/yr (8 TB) |
| 20 h | ~7.2 TB | **PRO** $1,549/yr (8 TB) |

Published tiers: Starter $129/yr (50 GB storage / 300 GB bandwidth) · Value $429/yr
(200 GB / 1.5 TB) · Express $699/yr (400 GB / 3 TB) · PRO $1,549/yr (800 GB / 8 TB) ·
Plus $2,999/yr · Premium $5,499/yr. Overage runs roughly **$0.09–0.29/GB bandwidth** and
**$0.70/GB storage** depending on tier — overage is expensive, so size up rather than out.

Two levers worth knowing before you pick: capping default playback quality at 720p roughly
halves the bill versus 1080p, and a gradual rollout (30 students, then 300) lets you measure
actual consumption before buying the big tier. **Recommendation: start on Value ($429) during
the build and soft launch, then size the real plan from measured data.**

### 4.2 Full service list

| Service | Plan | Cost | Why it's required |
|---|---|---|---|
| **Supabase** | Pro | **$25/mo** ($300/yr) | Free tier has **no backups** — your day-one requirement forces Pro. Also 8 GB DB, 100 GB storage, 250 GB egress, custom SMTP. |
| **VdoCipher** | Value → PRO | **$429–$1,549/yr** | DRM video. See sizing above. |
| **Vercel** | Pro | **$20/mo** ($240/yr) | Hobby is free but its ToS bars commercial use — you are selling courses, so Pro. |
| **Render** (or Railway) | Starter web service | **$7–25/mo** ($84–300/yr) | FastAPI + a nightly backup cron. Starter (512 MB) is genuinely enough for 300 students; Standard if PDF generation needs headroom. Railway is comparable at ~$5 base + usage. |
| **Stripe** | pay-per-use | **2.9% + $0.30** per transaction | No fixed fee. On $30k/yr of sales ≈ $900/yr. **India caveat in §1.G-IN** — Razorpay is ~2% domestic, a Merchant of Record ~5%. Budget 2–5% of revenue until the provider is settled. |
| **Resend** | Free → Pro | **$0–20/mo** | Free covers 3,000 emails/mo, which fits 300 students. Pro (50k) if you start marketing. |
| **Cloudflare R2** | pay-as-you-go | **~$1/mo** | Offsite encrypted DB backups. Zero egress fees. |
| **Upstash Redis** | Free → PAYG | **$0–10/mo** | Distributed rate limiting. Free tier likely sufficient. |
| **Sentry** | Developer free → Team | **$0–26/mo** | Free tier (5k errors) is fine to start. |
| **Domain** | .com | **~$15/yr** | |
| **Cloudflare** | Free (Pro optional) | **$0** (or $20/mo) | DNS, TLS, Turnstile captcha free. Pro only if you want managed WAF rules. |
| **PostHog** | Free tier | **$0** | Product analytics; free tier is generous. |
| **Better Stack** | Free | **$0** | Uptime monitoring + status page. |
| **GitHub Actions** | Free | **$0** | CI on a public/small private repo. |

### 4.3 Totals

| Scenario | Monthly | Annual |
|---|---|---|
| **Lean** (Value video, Render Starter, all free tiers) | ~$90 | **~$1,080** |
| **Realistic** (Express video, Render Standard, Resend Pro, Sentry Team) | ~$185 | **~$2,240** |
| **Heavy** (PRO video 8 TB, Cloudflare Pro, PITR) | ~$290 | **~$3,500** |

Plus **2–5 % of revenue** to the payment provider (see §1.G-IN — the range is wide until the
India provider question is settled), and one-off costs: commercial font licence $0–300,
privacy policy / terms review $0–500. If you go the Merchant-of-Record route, budget the
higher fee but delete the global tax-registration work.

**The headline:** ~$90–185/month all-in for 300 students, and video bandwidth is over half of
it. Nothing here is a per-seat cost, so the price barely moves between 100 and 300 students —
it moves with *hours watched*.

---

## 5. Assumptions & open questions

### 5.1 Assumptions I am making
If any of these is wrong, tell me before I start — several change the schema.

1. **Single publisher.** You are the only content creator. No multi-instructor marketplace,
   no revenue splits, no instructor onboarding.
2. **Students self-serve.** Individuals sign up and buy for themselves. No corporate bulk
   seats, no invoicing, no org accounts, no seat management.
3. ~~One-time purchase, lifetime access.~~ **Resolved (decision 1):** access policy is
   per-course. The first course is one-time purchase with lifetime access; the schema carries
   `access_type` on each course so later courses can be time-limited without a migration.
   Subscriptions remain out of scope.
4. **Pre-recorded content only.** No live classes, no Zoom integration, no scheduling.
5. **No community features in v1.** No discussion forums, no comments, no Q&A, no messaging.
6. **English only, single currency.** No i18n framework, no multi-currency pricing. (Worth
   revisiting given an Indian entity with possibly international students — INR vs USD
   pricing is question 9 below.)
7. **Responsive web only.** No native iOS/Android app. (Worth flagging: VdoCipher's strongest
   DRM story is in native apps; on web you get browser DRM, which is good but not identical.)
8. **Certificates are completion certificates**, not accredited credentials. No external
   registry (Credly/Accredible) integration.
9. **No drip scheduling, coupons, affiliates, or bundles in v1.** Coupons are the most likely
   of these to be wanted early — cheap to add later, cheaper to plan for now if you want it.
10. **No SCORM/xAPI/LTI.** Nobody is plugging this into another institution's LMS.
11. **Modest content volume** — on the order of 20–60 hours of video total. This drives the
    VdoCipher storage tier.
12. **You have no existing student data to migrate**, and no existing course content already
    hosted somewhere that needs importing.

### 5.2 Questions I need answered

**Scope and product**
1. ~~Access model~~ — **answered**: per-course, first course lifetime. See §0.1.
2. ~~Completion rule~~ — **answered**: all required lessons + all quizzes passed, no gating.
3. **Quiz retries** — I've defaulted to unlimited attempts with no time limit, since you chose
   no gating. Confirm, or give me a cap.
4. **Refund policy** — is there one, and should a refund immediately revoke access and any
   issued certificate? Yes
5. **How many courses and roughly how many hours of video** at launch? 1 course for now. With approximately 50 short videos.
6. **Is any of this connected to the NLP Limited site in this repo?** LMS is a separate project.

**Commercial and legal**
7. ~~Selling entity country~~ — **answered: India.** Follow-up:
   **has Stripe approved your account, or do you need to apply?** Not yet. This will be looked at soon.
8. **Where are your students — India, international, or both?** Both.
9. **Price point per course**, roughly, and **INR or USD**? This will be looked at later.

**Technical**
10. ~~Next.js or Vite SPA~~ — **answered: Next.js App Router.**
11. **Render or Railway?** Slight preference for Render — predictable flat pricing and
    built-in cron for the backup job, which you need. Railway has nicer DX and usage-based
    billing.
12. **Do you already have a VdoCipher account**, and is any content uploaded to it? No, account needs to be created.
13. **Do you have brand assets** — logo, colours, fonts, any existing design direction? Yes.
14. **Timeline and budget ceiling**, if there is one. Timeline to build is one week. Budget ceiling exists. Focus on pilot build first.

---

## 6. Build sequence

Proposed order once you give the go-ahead. Each phase ends somewhere demo-able.

| Phase | Contents |
|---|---|
| **0 — Foundations** | Monorepo, Supabase projects (dev/prod), migrations, CI, Sentry, env plumbing, backup cron + **first restore drill**. |
| **1 — Auth & design system** | Supabase Auth wired end-to-end, JWT verification in FastAPI, RBAC, design tokens and core components, app shell. |
| **2 — Content model & admin** | Course/module/lesson CRUD, ordering, TipTap lessons, VdoCipher upload, draft/publish. Point: you can author a full course with no code. |
| **3 — Learning experience** | Catalog, course page, player with DRM + watermark + OTP flow, progress heartbeats, resume, student dashboard. |
| **4 — Assessment & certificates** | Quiz builder, quiz runner, server-side grading, attempts, certificate PDF + verification page. |
| **5 — Payments** | Provider interface + Stripe adapter, hosted checkout, webhooks, idempotency, refunds, free-course enrolment, tax-inclusive pricing. **Gated on the Stripe-India answer (question 7)** — if it's unresolved by then I'll build the Razorpay adapter instead and keep Stripe as the second implementation. |
| **6 — Polish & hardening** | Every empty/error state, mobile pass at 360 px, accessibility audit, CSP and security headers, load sanity check, E2E suite, restore drill #2. |

Security work is not a phase — the checklist items land inside the phase that introduces the
surface they protect.
