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
  web/          Next.js frontend (not yet built)
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

## API

```bash
cd apps/api
uv venv .venv && . .venv/bin/activate
uv pip install -e ".[dev]"
cp .env.example .env          # defaults run against the mock video provider
uvicorn app.main:app --reload
```

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
