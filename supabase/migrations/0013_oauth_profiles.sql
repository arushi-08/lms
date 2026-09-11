-- 0013_oauth_profiles: populate a new profile from an OAuth provider's claims.
--
-- Signing in with Google produces an auth.users row whose raw_user_meta_data is
-- filled by the provider rather than by our signup form: `name` and `picture`
-- instead of the `full_name` our own form sends. Without this, every Google
-- account arrived with a blank name -- and the name is what gets printed on the
-- certificate.
--
-- Everything read here is attacker-controlled in the general case. A user can
-- write their own raw_user_meta_data through the Supabase client
-- (auth.updateUser({data: ...})), and an OAuth provider can return whatever it
-- likes. So this function reads exactly two display fields, validates both, and
-- reads nothing else. In particular it does not read `role`: role stays at the
-- column default, and the one way to become an admin is for someone with
-- database access to say so. A trigger that trusted a `role` key in user
-- metadata would be a self-service admin panel.

create or replace function public.profile_display_name(meta jsonb)
returns text language sql immutable
set search_path = pg_temp as $$
  -- Our own signup form sends full_name; Google sends name. Length-capped
  -- because nothing downstream (a certificate, an email, the grading queue)
  -- benefits from a megabyte of it, and the column is unbounded text.
  select nullif(left(trim(coalesce(
    nullif(trim(coalesce(meta ->> 'full_name', '')), ''),
    nullif(trim(coalesce(meta ->> 'name', '')), ''),
    ''
  )), 120), '');
$$;

create or replace function public.profile_avatar_url(meta jsonb)
returns text language sql immutable
set search_path = pg_temp as $$
  -- https only, and only where it parses as a plain absolute URL. The value ends
  -- up in an <img src>, where a `javascript:` or `data:` URL has no business
  -- being even if today's renderer happens to ignore it. Anything else is
  -- dropped rather than cleaned: a rejected avatar costs a placeholder image,
  -- while a half-sanitised one costs a bug nobody sees coming.
  select case
    when candidate ~ '^https://[A-Za-z0-9._~%-]+(:[0-9]+)?(/[^[:space:]<>"''\\]*)?$'
      then candidate
    else null
  end
  from (
    select nullif(left(trim(coalesce(
      nullif(trim(coalesce(meta ->> 'avatar_url', '')), ''),
      nullif(trim(coalesce(meta ->> 'picture', '')), ''),
      ''
    )), 500), '') as candidate
  ) _c;
$$;

create or replace function public.handle_new_user()
returns trigger language plpgsql security definer
set search_path = public, pg_temp as $$
begin
  insert into public.profiles (id, email, full_name, avatar_url)
  values (
    new.id,
    new.email,
    public.profile_display_name(new.raw_user_meta_data),
    public.profile_avatar_url(new.raw_user_meta_data)
  )
  -- do nothing, not do update: when Supabase links a Google identity to an
  -- existing account there is no second insert, and if there were, the
  -- provider's copy of the name should not silently overwrite the one the
  -- student typed.
  on conflict (id) do nothing;
  return new;
end;
$$;

-- Backfill names that the old version could not read, and only those: a name
-- already set is left exactly as it is.
update public.profiles p
   set full_name = public.profile_display_name(u.raw_user_meta_data)
  from auth.users u
 where u.id = p.id
   and p.full_name is null
   and public.profile_display_name(u.raw_user_meta_data) is not null;
