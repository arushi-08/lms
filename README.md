# LMS Platform

Pilot build. Design lives in [`../docs/lms/PLAN.md`](../docs/lms/PLAN.md); pilot scope and
free-tier decisions in [`../docs/lms/PILOT.md`](../docs/lms/PILOT.md).

This directory is self-contained and imports nothing from the surrounding site. To move it
into its own repository later:

```bash
git subtree split -P lms -b lms-only
```

## Layout

```
lms/
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
for f in lms/supabase/migrations/*.sql; do psql -v ON_ERROR_STOP=1 -f "$f"; done
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
./lms/supabase/tests/run.sh
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
