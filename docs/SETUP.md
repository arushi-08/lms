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
3. **Enable the access-token hook**: Authentication → Hooks → Customize Access Token →
   `public.custom_access_token_hook`. Without this no JWT carries `user_role`, and every
   admin RLS policy silently evaluates to false. Nothing errors; admin features just quietly
   do not work.
4. Sign up through the app, then promote yourself in the SQL editor:
   ```sql
   update public.profiles set role = 'admin' where email = 'you@example.com';
   ```
   Sign out and back in — the role only reaches your token on the next refresh.
5. Auth settings worth changing from the defaults: require email confirmation, minimum
   password length 10, enable the leaked-password check, turn on Turnstile captcha.

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
