-- 0012_admin_mfa: mandatory TOTP for admins, mirrored where the API can read it.
--
-- Supabase (GoTrue) does the actual second factor: enrollment, the QR code, the
-- shared secret, the challenge and the code check all happen between the browser
-- and Supabase. This service never sees a TOTP secret or a six-digit code, which
-- is the whole reason admin MFA is a small change rather than a crypto project.
--
-- What the application needs to decide is narrower: *may this request act as an
-- admin*. That takes two facts.
--
--   1. Did this session actually present the second factor? The JWT says so, in
--      the `aal` claim -- aal1 is one factor, aal2 is two.
--   2. Is the factor it presented the one we expect? The token does not say
--      which factor was used, so an `aal2` claim on its own is satisfied by any
--      factor the account holds -- including one an attacker enrolled after
--      stealing the password. So we pin the factor: the first verified TOTP
--      factor is recorded, and admin access requires that the account's set of
--      verified factors is still exactly that one.
--
-- Fact 2 lives here. auth.mfa_factors is owned by supabase_auth_admin, and this
-- service must not depend on cross-schema privileges on every request, so a
-- trigger mirrors the state into public.profiles. That also means the admin gate
-- costs no extra query: the role read it already does now returns both.

alter table public.profiles
  add column mfa_factor_id       uuid,
  --: Every currently verified TOTP factor. Compared against the pin above, so an
  --: added factor is a mismatch rather than a second key to the same door.
  add column mfa_verified_factors uuid[] not null default '{}'::uuid[],
  add column mfa_verified_at     timestamptz;

comment on column public.profiles.mfa_factor_id is
  'Pinned TOTP factor. Set once, on first verification; moved only by an '
  'explicit rotation from an already-stepped-up admin, or by scripts/reset_admin_mfa.py.';

-- Recompute one user's mirrored factor state from the source of truth.
--
-- security definer because the caller is GoTrue's own transaction, whose role
-- has no business writing public.profiles.
create or replace function public.sync_mfa_factor_state(p_user_id uuid)
returns void language plpgsql security definer
set search_path = public, pg_temp as $$
declare
  verified uuid[];
  pinned   uuid;
begin
  select coalesce(array_agg(f.id order by f.id), '{}'::uuid[])
    into verified
  from auth.mfa_factors f
  where f.user_id = p_user_id
    and f.status::text = 'verified'
    and f.factor_type::text = 'totp';

  select p.mfa_factor_id into pinned
  from public.profiles p where p.id = p_user_id;

  -- Trust on first use: the first factor an account verifies becomes the pinned
  -- one. Later factors do not move the pin -- if they did, enrolling a new
  -- authenticator would be enough to become the trusted one, and the pin would
  -- protect nothing.
  if pinned is null and array_length(verified, 1) = 1 then
    pinned := verified[1];
  end if;

  update public.profiles p
     set mfa_factor_id       = pinned,
         mfa_verified_factors = verified,
         mfa_verified_at      = case
           when array_length(verified, 1) > 0 then coalesce(p.mfa_verified_at, now())
           else null
         end
   where p.id = p_user_id
     and (p.mfa_factor_id is distinct from pinned
       or p.mfa_verified_factors is distinct from verified);
end;
$$;

revoke execute on function public.sync_mfa_factor_state(uuid) from public, anon, authenticated;

create or replace function public.handle_mfa_factor_change()
returns trigger language plpgsql security definer
set search_path = public, pg_temp as $$
declare
  target uuid := coalesce(new.user_id, old.user_id);
  before uuid[];
  after  uuid[];
begin
  select p.mfa_verified_factors into before from public.profiles p where p.id = target;
  perform public.sync_mfa_factor_state(target);
  select p.mfa_verified_factors into after  from public.profiles p where p.id = target;

  -- Audited because a factor disappearing from an admin account is the first
  -- move in taking it over, and an unexplained one should be findable later.
  -- The log is insert-only (0008), so this record cannot be tidied away.
  if before is distinct from after then
    insert into public.audit_log (actor_id, action, entity_type, entity_id, diff)
    values (
      target, 'mfa.factors_changed', 'profile', target::text,
      jsonb_build_object('before', to_jsonb(before), 'after', to_jsonb(after))
    );
  end if;

  return null;
end;
$$;

-- after, and for each row: the mirror should reflect a committed change, and a
-- failure here must not be able to block someone from enrolling a factor.
create trigger on_mfa_factor_change
  after insert or update or delete on auth.mfa_factors
  for each row execute function public.handle_mfa_factor_change();

-- Backfill, so an admin who enrolled before this migration is not asked to
-- enroll again.
do $$
declare
  u record;
begin
  for u in select id from public.profiles loop
    perform public.sync_mfa_factor_state(u.id);
  end loop;
end
$$;

-- ------------------------------------------------------------------- RLS ----
-- The assurance level the current request's JWT asserts. 'aal1' on anything
-- unexpected: no claim, no session, malformed claims. Least privilege by
-- default, same as jwt_role().
create or replace function public.jwt_aal()
returns text language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'aal',
    'aal1'
  );
$$;

-- Admin rights through PostgREST now also require the second factor. The API
-- connects with the service role and bypasses RLS, so this changes nothing for
-- the application -- it closes the browser-side path, where an admin's anon-key
-- session could otherwise read every profile and every submission with a
-- password alone.
--
-- Note what this does *not* check: which factor. That is deliberate -- a policy
-- cannot afford the query, and public.profiles is the place where the pin is
-- already compared, on every admin request. RLS is the second line here too.
create or replace function public.is_admin()
returns boolean language sql stable as $$
  select public.jwt_role() = 'admin' and public.jwt_aal() = 'aal2';
$$;

-- The mirrored columns are readable by their owner (the security page shows
-- enrollment state) but not writable by anyone: they are not in the update
-- grant, so a crafted PATCH cannot pin an attacker's own factor.
grant select (mfa_factor_id, mfa_verified_factors, mfa_verified_at)
  on public.profiles to authenticated;
