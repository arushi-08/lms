# Launch readiness — pilot to 50–100 enrolled students

**Companion to `PILOT.md`.** That document is what the pilot week built. This one is a
critical assessment of what stands between that and real students with real money, real PII
and real expectations.

Written after auditing the repository and the live CI history, not from memory. Every claim
below is marked with how it was checked. Section 6 lists what could **not** be verified from
here, so it is not mistaken for fact.

---

## 1. The headline

Three things that read as *done* are not done. Each was listed as in-scope or
non-negotiable, and each would be discovered by a student rather than by us.

| | Believed | Actual | Evidence |
|---|---|---|---|
| **Backups** | "automated from day one" (`PILOT.md` §5) | **Zero backups exist.** 76 consecutive nightly failures | Run log: `##[error]LMS_DATABASE_URL is not set` |
| **Certificates** | "certificates with public verification" (`PILOT.md` §3) | **Never issued.** No code writes the table; no verification page | No `insert into certificates` anywhere in `apps/api`; route list has no `/verify` |
| **Deployment** | Render + Vercel | **Nothing is deployed.** Runs on one laptop | No `render.yaml`, `vercel.json` or `Dockerfile` in the repo |

The backup one is the serious one. The requirement was explicit from the first brief, the
workflow was written on day one, and it has failed every night since because a repository
secret was never set. The failure is silent unless someone opens the Actions tab — GitHub
emails the repo owner on scheduled-workflow failures, but that is a mail nobody reads after
the seventieth. **There is no copy of the pilot database anywhere.** Restore verification is
failing too (12 runs), which is the check that was supposed to catch exactly this.

Certificates are the embarrassing one. The homepage promises "a certificate that means you
actually finished". The signup form says your name is "Printed on your certificate". The
dashboard queries the table and renders a section for them. Nothing ever inserts a row, so
the first student to finish the course gets an empty space where the reward is.

---

## 2. What is genuinely solid

Worth stating plainly, because the list above is not the whole picture and the security
work is well ahead of where a project this age usually is.

- **Authorisation is layered and tested.** Deny-by-default RLS on 19 tables, 86 adversarial
  checks in CI phrased as attacks a signed-in student could actually attempt. The API
  re-reads the role from the database on every admin request rather than trusting the token.
- **Admin MFA is real.** TOTP required, with the enrolled factor pinned, so an attacker
  holding the admin password cannot enroll their own authenticator and walk in.
- **216 API tests and the RLS suite run on every push**, plus CSP, redirect-guard, colour
  contrast and secret-scanning checks. CI is green.
- **Server-side progress clamping**, so watch time cannot be forged by a crafted request.
- **Rate limiting** on every write path.

None of this needs revisiting before launch. The gaps are elsewhere.

---

## 3. Blockers — a student cannot be onboarded until these are done

### 3.1 Backups (critical, hours)

Set the five repository secrets the workflow documents: `LMS_DATABASE_URL`,
`LMS_AGE_RECIPIENT`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`.
Then run it manually (`workflow_dispatch`) and **watch it pass**, then let restore
verification prove the dump actually restores.

Do this first, before anything else on this list, and before a single student signs up. The
cost of the other items is time; the cost of this one is other people's data.

A second change is worth making while in there: the job reports failure into the Actions log
and nowhere else. Seventy-six silent failures is the evidence that this is not enough. Send
failures somewhere a human sees them.

### 3.2 Video: the mock provider cannot go to production (large)

`VIDEO_PROVIDER=mock` serves unencrypted files from the API's own filesystem. That fails the
original hard requirement — DRM, no student downloads — and the production config guard
refuses to start on it, so this is a literal blocker, not a judgement call.

Switching to VdoCipher is one environment variable *by design*, but that claim has never
been tested against the real API: `VdoCipherProvider` exists and is unit-tested against a
mocked transport, and has never spoken to VdoCipher. Budget real time for the first contact
— upload, encoding states, OTP, watermark, player embed — not the five minutes the env-var
story implies.

There is a second reason this matters at 50–100 students: with the mock, **every video byte
flows through the API**. The latency work in `AUTH_AND_SCALE.md` assumed video bytes never
touch it, which is true of VdoCipher and false of the mock. Launching on the mock would
invalidate the only performance analysis this project has.

### 3.3 Email (critical, small)

Supabase's built-in email sender is a testing convenience with a low hourly cap — low enough
that it was already hit during setup, which locked out the password-reset route for an hour.
Signup confirmation for 50–100 students will exhaust it immediately, and the failure mode is
students who never receive a confirmation link and cannot sign in.

Configure custom SMTP before launch. `SETUP.md` §1.8 already says this; it is still not done.

### 3.4 Certificates (medium)

Either implement them or remove the promise. Implementing is the smaller job than it looks:
`completion.recompute()` already computes the one boolean that matters and is the single
place every completion path funnels through. What is missing is the insert, a serial, the
public verification page the pilot scoped, and the revoke path on refund.

What must not happen is launching with the homepage and the signup form promising something
the product does not do.

### 3.5 Deployment (medium)

Nothing exists yet: no service definitions, no environment configuration, no deploy
pipeline. Decisions that are still open and should not be made under time pressure on launch
day:

- **Region.** Supabase is `us-west-2` (Oregon). Render must match it. This is the largest
  single latency lever measured, and getting it wrong costs ~480 ms per request with
  identical code.
- **Paid tiers.** Render's free tier spins down after idle; a ~50 s cold start ends any
  response-time commitment. Supabase free has no backups and pauses after ~7 days idle.
- **Secrets.** `SUPABASE_SERVICE_ROLE_KEY` goes into Render's environment, nowhere else.

---

## 4. Significant gaps — not blockers, but do not discover these in week two

**Payments.** There is no Stripe code at all — only unused settings. `POST /enrollments`
returns 402 for any course where `is_free` is false, with no path forward. If anything is to
be charged for, this is a build, not a configuration. If everything is free at launch, say so
explicitly and the whole item disappears.

**Error monitoring.** `sentry_dsn` is a setting that nothing reads. In production, an
exception reaching a student is currently invisible to us. This is the cheapest item on the
list and the one that most changes how the first fortnight feels.

**No end-to-end tests, and no frontend tests at all.** 216 API tests cover the backend well;
the browser has none. The bugs that actually reached a user during the pilot — the CSP that
blocked every API call, the player sending a position where cumulative time was expected, the
abandoned-MFA-enrolment jam — were all in that uncovered layer. Playwright is already a
devDependency and unused. One test that signs in, plays a lesson, passes a quiz and sees
progress move would have caught most of them.

**Legal pages.** No privacy policy, no terms, no data-deletion route. `PILOT.md` §1 notes
students will be in India and internationally, which makes this real rather than decorative,
particularly once money is involved.

**In-app notifications.** The table exists; nothing writes to it. Fine to defer, worth
knowing it is not wired.

**Operational items already in flight:** admin TOTP is not yet enrolled (the admin panel is
closed until it is), and Google sign-in is not yet configured in Supabase.

---

## 5. Recommended order

Ordered by what goes wrong if it is skipped, not by effort.

**Before any student account exists**
1. Backups: set the secrets, prove a dump, prove a restore, route failures to a human.
2. Custom SMTP.
3. Sentry — ten minutes, and the difference between hearing about a bug from logs or from a
   student.

**Before launch**
4. VdoCipher: real account, real upload of the real clips, real playback. Allow for this
   taking several days, not an afternoon.
5. Deploy to Render (Oregon) and Vercel on paid tiers; run the existing load test against
   staging on the real network path, because the only numbers we have are from a laptop.
6. Certificates: issue, verify, revoke — or remove the claim from the marketing copy.
7. One end-to-end test over the critical path, run in CI.
8. Legal pages.

**Decide before step 4, because it changes scope**
9. Paid or free at launch. Paid means Stripe, refunds, invoices, tax and a Vercel Pro
   licence; free means none of it. Nothing else in this plan depends on the answer, and
   everything in a payments build does.

**After launch**
10. Admin timing middleware and the `/metrics` summary from `AUTH_AND_SCALE.md` §Phase 3 —
    the SLO is currently an opinion.
11. Collapse the progress heartbeat's six round trips to two, if the real numbers say so.

---

## 6. What could not be verified from here, and should not be taken as fact

Stated explicitly so none of it is mistaken for a checked claim.

- **Third-party pricing and free-tier limits.** `PILOT.md` §5 quotes VdoCipher at ~$429/yr,
  Supabase Pro at $25/mo, Render Starter at $7/mo, Vercel Pro at $20/mo, and says Vercel's
  Hobby terms prohibit commercial use. Those figures are from the pilot write-up and were not
  re-checked; the session this audit was written in has no network access to those vendors.
  Re-check all of them before committing to a monthly cost.
- **Supabase's exact built-in email rate limit.** That it is low and was hit in practice is
  from this project's own history; the specific number is not verified.
- **Whether `VdoCipherProvider` works against the real API.** Its unit tests use a mocked
  transport. Nothing here has ever talked to VdoCipher.
- **Current performance under real conditions.** The p95 of 56 ms at 10–15 rps was measured
  on a laptop against a local database. The deployed number is unknown and will be worse.
- **Whether 50–100 students is concurrent or total.** The analysis in `AUTH_AND_SCALE.md`
  assumed 100 *concurrent*. If that is the total enrolled, actual peak load is far lower and
  the infrastructure question is smaller than it looks.
