# Setup checklist

What has to exist outside the repository before the pilot can run. Everything here is free
tier. Nothing in this list is blocking the build — the code runs today against the mock video
provider and a local Postgres — but each item unblocks the next slice.

## 1. Supabase (free) — *needed to run anything against real auth*

1. Create a project. Note the project ref, URL and `anon` key.
2. Apply the schema:
   ```bash
   supabase link --project-ref <ref>
   supabase db push
   ```
3. **Check what the public key can reach**, before anything else. Paste
   `supabase/tests/check_rls_enabled.sql` into the SQL editor. Any table with the
   verdict `EXPOSED` is readable and writable by anyone holding your anon key — which
   ships in the browser and is therefore public. Fix those before real accounts exist.
4. **Enable the access-token hook**: Authentication → Hooks → Customize Access Token →
   `public.custom_access_token_hook`. Without this no JWT carries `user_role`, and every
   admin RLS policy silently evaluates to false. Nothing errors; admin features just quietly
   do not work.
5. **Set the URL configuration.** Authentication → URL Configuration:
   - Site URL: `http://localhost:3000` while developing, your real domain later.
   - Redirect URLs: add `http://localhost:3000/**`, plus your deployed domain.

   Skip this and confirmation and password-reset links redirect somewhere else —
   usually straight back to the login page with no explanation, which reads as a
   broken app rather than a missing setting.

6. **Create your account.** Either sign up at `/signup` in the running app, or in
   Authentication → Users → **Add user → Create new user**, with a password and
   **Auto Confirm User** ticked.

   Use *Create new user*, not *Send invitation*. An invitation sets no password at
   all, so the account shows as confirmed while every sign-in attempt returns
   `invalid_credentials` — which looks like a wrong password rather than a missing
   one. If you have already hit that, Authentication → Users → the user → **Reset
   password** fixes it, as does `/forgot-password` in the app.

7. Promote yourself in the SQL editor:
   ```sql
   update public.profiles set role = 'admin' where email = 'you@example.com';
   ```
   Sign out and back in — the role only reaches your token on the next refresh.

8. **Configure custom SMTP before you rely on any email.** Authentication →
   Emails → SMTP Settings. Supabase's built-in sender allows only a couple of
   messages an hour — it is a testing convenience, not a mail service, and the
   limit is fixed until you point it at your own SMTP.

   You will hit this during setup, not at launch: two reset attempts is enough,
   and once exhausted every email route is closed for an hour, including the one
   you need to get back in. Resend's free tier (3,000/month) takes about ten
   minutes to wire up and the platform needs it regardless.

   Until then, `scripts/set_password.py` sets a password through the Admin API
   with no email involved.

9. Auth settings worth changing from the defaults: require email confirmation, minimum
   password length 10, enable the leaked-password check, turn on Turnstile captcha.

10. **Verify from outside.** With the project reachable from your machine:
   ```bash
   export SUPABASE_URL=https://<ref>.supabase.co
   export SUPABASE_ANON_KEY=<anon key>
   python3 scripts/verify_supabase.py --probe-writes
   ```
   This probes the live project holding nothing but the public key and asserts the answer
   key, payments, the audit log and paid lesson content are all unreachable. It refuses to
   report success if the schema is missing or the project is unreachable — "I could not
   check" is never reported as "it is fine".

Send me the **URL and anon key**. The `service_role` key goes straight into Render and GitHub
secrets — don't paste it into chat, and if it ever lands in a browser bundle, rotate it.

## 2. GitHub secrets — *needed for backups to start running*

Backups are a day-one requirement and the free Supabase tier provides none, so they run from
this repository via GitHub Actions. Set these under Settings → Secrets → Actions:

| Secret | What it is |
|---|---|
| `LMS_DATABASE_URL` | Supabase connection string (pooler URL is fine) |
| `LMS_AGE_RECIPIENT` | age **public** key — `age-keygen -o key.txt`, then copy the `public key:` line |
| `LMS_AGE_SECRET_KEY` | the contents of `key.txt`. Used only by the restore-check job |
| `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | Cloudflare R2, free tier |

Keep `key.txt` somewhere you will still have it after losing your laptop — a backup you
cannot decrypt is not a backup. The workflow only ever holds the public key, so a compromised
runner cannot read the backup history.

Set a **30-day lifecycle rule** on the R2 bucket for retention. The workflow deliberately
cannot delete objects.

Then run **LMS nightly backup** manually once (Actions → Run workflow) to confirm it works,
rather than finding out at 02:17.

## 3. VdoCipher — *needed only when real DRM playback matters*

The build uses `VIDEO_PROVIDER=mock` until this exists. When you create the account:

1. Set `VIDEO_PROVIDER=vdocipher` and `VDOCIPHER_API_SECRET` in the backend environment.
2. In the VdoCipher dashboard: enable DRM, **disable offline download**, and restrict the
   player domain allowlist to the production and preview domains.
3. Upload the 4–5 sample clips and confirm the watermark shows the viewer's email.

Start on the trial, then size the plan from measured bandwidth — see `PLAN.md` §4.1. Do not
buy a tier before you have a week of real numbers.

## 4. Render (free) — *needed for a deployed backend*

Web service from `apps/api`, start command `uvicorn app.main:app --host 0.0.0.0 --port
$PORT`. Set every variable from `.env.example`. Free instances spin down after ~15 minutes
idle and cold-start in roughly a minute; fine for a pilot, upgrade to Starter ($7) at launch.

## 5. Vercel (free) — *needed for a deployed frontend*

Hobby is free but its terms bar commercial use, so it is fine while nothing is for sale and
needs to become Pro ($20/mo) the day you charge.

## 6. Stripe — *deferred*

Not in the pilot. Payments are out of scope until the entity is approved (`PLAN.md` §1.G-IN).
Worth starting the application now regardless, since approval is the long pole.

---

## Troubleshooting sign-in

The login form shows one generic message for every failure, so it cannot be used to test
which email addresses are registered. To see the real reason:

```bash
./scripts/check_auth.sh you@example.com 'your-password'
```

This calls Supabase directly, prints its actual error, and names the likely cause. On
success it decodes the token and reports whether `user_role` is present — a missing
access-token hook is silent everywhere else. In development the app also logs the real
error to the browser console.

To get in without email at all — useful when the hourly email limit is spent:

```bash
export SUPABASE_URL=https://<ref>.supabase.co
export SUPABASE_SERVICE_ROLE_KEY=<service role key>   # Project Settings > API
python3 scripts/set_password.py you@example.com 'a-strong-password'
```

That key bypasses every RLS policy. Pass it for one command, keep it out of
`.env.local` (which is compiled into the browser bundle), never commit it, and
rotate it in the dashboard if it is ever exposed.

| What you see | Usually means |
|---|---|
| `invalid_credentials` | No password was ever set — the account came from an invitation. See step 6. |
| `Email not confirmed` | Confirm the address, or tick Auto Confirm User. |
| `Email logins are disabled` | Authentication → Providers → Email is switched off. |
| `Invalid API key` | The anon key belongs to a different project than the URL. |
| Reset link lands on the login page | URL Configuration is unset. See step 5. |
| `rate limit exceeded` on a reset or signup | The built-in email sender allows about two messages an hour. Configure custom SMTP (step 8), or set the password with `scripts/set_password.py`, which sends nothing. |
| Reset link worked once, now does not | Recovery links are single-use and expire after an hour. Request another — or avoid email entirely with `scripts/set_password.py`. |
