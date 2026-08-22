-- 0002_identity: profiles mirror of auth.users, plus the access-token hook that
-- carries the role into the JWT so RLS can read it without a join.

create table public.profiles (
  id         uuid primary key references auth.users (id) on delete cascade,
  email      text not null,
  full_name  text,
  avatar_url text,
  role       public.user_role not null default 'student',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index profiles_email_idx on public.profiles (lower(email));
create index profiles_role_idx  on public.profiles (role) where role = 'admin';

create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

-- A profile row must exist for every auth user; creating it in a trigger means
-- there is no window where a signed-up user has no profile.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer
set search_path = public, pg_temp as $$
begin
  insert into public.profiles (id, email, full_name)
  values (
    new.id,
    new.email,
    nullif(trim(coalesce(new.raw_user_meta_data ->> 'full_name', '')), '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Supabase custom access token hook: stamps user_role into every issued JWT.
-- Must be enabled in the dashboard (Auth > Hooks) or config.toml.
create or replace function public.custom_access_token_hook(event jsonb)
returns jsonb language plpgsql stable
set search_path = public, pg_temp as $$
declare
  claims    jsonb;
  found_role public.user_role;
begin
  select p.role into found_role
  from public.profiles p
  where p.id = (event ->> 'user_id')::uuid;

  claims := coalesce(event -> 'claims', '{}'::jsonb);
  claims := jsonb_set(claims, '{user_role}', to_jsonb(coalesce(found_role, 'student')::text));

  return jsonb_set(event, '{claims}', claims);
end;
$$;

grant usage  on schema public to supabase_auth_admin;
grant execute on function public.custom_access_token_hook(jsonb) to supabase_auth_admin;
revoke execute on function public.custom_access_token_hook(jsonb) from authenticated, anon, public;
grant select on public.profiles to supabase_auth_admin;
