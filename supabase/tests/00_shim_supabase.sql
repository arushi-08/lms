-- Local-only shim reproducing the parts of a Supabase project that the
-- migrations depend on: the auth schema, the three PostgREST roles, and
-- auth.uid()/auth.jwt() reading from the request.jwt.claims GUC.
--
-- This exists so migrations can be applied and RLS actually exercised in CI
-- against a plain Postgres container. It is never applied to a real project.

create extension if not exists pgcrypto;

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin noinherit;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'supabase_auth_admin') then
    create role supabase_auth_admin nologin noinherit;
  end if;
end
$$;

grant usage on schema public to anon, authenticated, service_role;

create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role, supabase_auth_admin;

create table if not exists auth.users (
  id                 uuid primary key default gen_random_uuid(),
  email              text,
  raw_user_meta_data jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);

create or replace function auth.uid()
returns uuid language sql stable as $$
  select nullif(
    coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub', ''),
    ''
  )::uuid;
$$;

create or replace function auth.jwt()
returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb, '{}'::jsonb);
$$;

-- GoTrue's MFA factor table, enough of it for 0012's trigger to be real.
-- The enum types are declared with the same names GoTrue uses, and the trigger
-- casts to text rather than comparing enum values, so a rename upstream shows up
-- as a test failure here rather than a silent mismatch in production.
do $$
begin
  if not exists (select 1 from pg_type where typname = 'factor_type'
                   and typnamespace = 'auth'::regnamespace) then
    create type auth.factor_type as enum ('totp', 'webauthn', 'phone');
  end if;
  if not exists (select 1 from pg_type where typname = 'factor_status'
                   and typnamespace = 'auth'::regnamespace) then
    create type auth.factor_status as enum ('unverified', 'verified');
  end if;
end
$$;

create table if not exists auth.mfa_factors (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users (id) on delete cascade,
  friendly_name text,
  factor_type  auth.factor_type not null default 'totp',
  status       auth.factor_status not null default 'unverified',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
