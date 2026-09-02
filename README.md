# LMS Platform

A course platform: FastAPI backend, Supabase (Postgres + Auth + RLS), VdoCipher DRM video,
Next.js frontend.

| Document | What it covers |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Target architecture, schema, security checklist, costs |
| [`docs/PILOT.md`](docs/PILOT.md) | Pilot scope, free-tier decisions, what is deferred |
| [`docs/SETUP.md`](docs/SETUP.md) | External accounts and secrets, in unblocking order |

## Layout

```
supabase/
  migrations/   schema + RLS, applied in filename order (source of truth)
  tests/        Supabase shim + adversarial RLS suite
apps/
  api/          FastAPI backend
  web/          Next.js frontend
```

## Database

The migrations are the schema's single source of truth. Nothing is clicked into the Supabase
dashboard — if it isn't in `supabase/migrations`, it doesn't exist.

```bash
# apply to a Supabase project
supabase link --project-ref <ref>
supabase db push

# or against any Postgres
for f in supabase/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -f "$f"; done
```

### After the first deploy

Two things are deliberately not automated, because both are ways to accidentally ship a
backdoor:

1. **Enable the access-token hook.** Supabase dashboard → Authentication → Hooks → Customize
   Access Token → `public.custom_access_token_hook`. Without it, no JWT carries `user_role`
   and every admin RLS policy silently evaluates to false.
2. **Promote the first admin,** by hand, in the SQL editor:
   ```sql
   update public.profiles set role = 'admin' where email = 'you@example.com';
   ```
   The user must sign up through the normal flow first, and must sign out and back in for the
   new role to appear in their token.

## Tests

```bash
./supabase/tests/run.sh
```

`run.sh` **drops and recreates** its target database, so it refuses to run against any
non-local host. Pointing your Supabase pooler URL at it — the obvious way to "test against
the real thing" — is exactly the accident that guard exists to stop.

To check a *live* project instead, both of these are read-only:

```bash
# from the Supabase SQL editor: which tables lack RLS
supabase/tests/check_rls_enabled.sql

# from your machine: what the public anon key can actually reach
SUPABASE_URL=... SUPABASE_ANON_KEY=... python3 scripts/verify_supabase.py
```

Applies the migrations to a scratch database and runs 38 adversarial RLS checks — each one an
attack a signed-in student could really attempt with the public anon key: reading the answer
key, reading another student's records, self-promoting to admin, forging progress, issuing
themselves a certificate. Add a check whenever you add a policy.

## Security invariants

These are enforced by tests, not by convention. Breaking one should fail CI.

| Invariant | Enforced by |
|---|---|
| `quiz_options` and `quiz_questions.correct_answers` are unreachable with the anon key | no grant + `01_rls_test.sql` |
| `lessons.content` and `lessons.video_id` are unreachable with the anon key | column grant + tests |
| Students can read only their own enrolment, progress, attempts, certificates | RLS + tests |
| Students cannot write enrolment, progress, attempts or certificates at all | no grant + tests |
| A student cannot change their own `role` | column grant + tests |
| An expired enrolment loses entitlement immediately | `has_active_enrollment()` + tests |
| The audit log accepts no update or delete from any role | no grant + tests |

## Running it

Both halves are needed: the admin panel and the player call the API, so the frontend alone
renders "Could not reach the API".

```bash
./scripts/dev.sh          # API on :8000, web on :3000, Ctrl-C stops both
```

First time only:

```bash
cd apps/api && uv venv .venv && . .venv/bin/activate && uv pip install -e '.[dev]'
cp .env.example .env      # fill in SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL

cd ../web && npm install
cp .env.example .env.local # fill in NEXT_PUBLIC_SUPABASE_URL and _ANON_KEY
```

`DATABASE_URL` is Supabase → Project Settings → Database → Connection string →
**Transaction pooler** (port 6543), not the direct connection. The free tier has very few
direct connections and a restarting dev server will exhaust them. If your database password
contains `@ : / ?` or `#`, percent-encode it or the URL will parse wrongly.

`scripts/dev.sh` checks both `.env` files and both dependency trees exist before starting,
and says exactly what is missing rather than failing halfway. Ports are overridable:
`API_PORT=8001 WEB_PORT=3001 ./scripts/dev.sh`.

It runs on macOS, Linux and Windows (Git Bash): no `setsid`, no bash 4+ syntax (macOS still
ships bash 3.2), and it finds the virtualenv in `Scripts/` as well as `bin/`. If you would
rather run the two halves in separate terminals, `uvicorn app.main:app --reload` from
`apps/api` and `npm run dev` from `apps/web` do the same thing.

## API

```bash
cd apps/api
uv venv .venv && . .venv/bin/activate
uv pip install -e ".[dev]"
uvicorn app.main:app --reload   # or use scripts/dev.sh to run both halves
```

Settings resolve `.env` relative to `apps/api/`, not to the working directory, so the
service loads the same configuration wherever it is started from.

### Tests

```bash
pytest                        # 103 tests
ruff check app tests
```

Unit tests cover grading and progress rules as pure functions. Integration tests run against
a real Postgres with the real migrations applied (via the same shim the RLS suite uses) and
real HS256 tokens through the real verification path — they skip automatically if no local
Postgres is reachable.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| `GET` | `/healthz` | liveness — never touches the database |
| `GET` | `/readyz` | readiness — checks the pool, 503 when down |
| `POST` | `/api/lessons/{id}/playback` | entitlement check → concurrency cap → watermarked OTP |
| `POST` | `/api/lessons/{id}/progress` | heartbeat, clamped server-side |
| `GET` | `/api/quizzes/{id}` | questions with the answer key absent by construction |
| `POST` | `/api/quizzes/{id}/attempts` | server-side grading |

### Where authorisation lives

`resolve_entitlement` in `app/security/deps.py` is the single decision point for "may this
user touch this lesson". It is called explicitly by each route rather than applied as a
decorator, so the check sits next to the thing it protects. If you add a route that reads
lesson content, call it.

The service authenticates to Postgres with the service role, which **bypasses RLS**. That is
deliberate — this is the component trusted to write enrolment and progress — but it means a
route that forgets its entitlement check is wide open. RLS is the backstop for the browser's
own key, not for this service.

## Admin

`/admin` is gated three times over: middleware requires a session, the admin layout
requires the admin role, and every `/api/admin/*` route re-reads `profiles.role` from the
database. The last one is what actually protects the data — an admin claim in a token buys
nothing on its own, and there is a test that forges one and still gets 403.

Adding content needs no code changes: create a course, add modules and lessons, upload video,
publish. Courses start as drafts and are invisible until published.

### Authoring rules worth knowing

| Rule | Why |
|---|---|
| A course cannot be published until it has a lesson | An empty course in the catalog is worse than no course |
| Reordering must send the complete ordering | A partial list leaves duplicate or missing positions and produces an order nobody chose |
| A course with enrolled students cannot be deleted | The cascade would take their progress and certificates too — unpublish instead |
| Revoking an enrolment sets a status, never deletes | So a mistake stays undoable |
| `PATCH` on a course cannot change `status` | Otherwise renaming a course could publish it |

### Video

The browser uploads straight to the provider; the file never passes through the API. With
`VIDEO_PROVIDER=mock` the flow is identical to the real one — ticket, upload, poll for
encoding — so the code exercised in development is the code that runs in production. The
mock even fakes encoding latency, because "uploaded but not yet playable" is a real state
the UI has to render.

Reordering uses up/down buttons rather than drag-and-drop: they work with a keyboard, a
screen reader and on a phone. Drag can be layered on later without touching the API, which
takes the complete ordering either way.

## Content Security Policy

`apps/web/csp.mjs` builds the policy; `next.config.ts` serves it on every response.

`connect-src` is generated from `NEXT_PUBLIC_API_URL`, because the browser calls the backend
directly for playback grants, progress, quiz submission and every admin mutation. If that
origin is missing the browser refuses those requests **before sending them** — nothing
reaches the API log, and `fetch` reports only "Failed to fetch". It presents as a dead
backend while the backend is perfectly healthy.

`node apps/web/scripts/check-csp.mjs` asserts the policy still permits what the app needs,
and runs in CI. Add a check there whenever the app starts talking to a new origin.

Deploying to a domain? Set `NEXT_PUBLIC_API_URL` **at build time** — the header is baked
during `next build`, not read per request.
