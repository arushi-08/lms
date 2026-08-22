-- 0001_init: extensions, enums, and shared helper functions.
--
-- Authorization model note (read this before touching the helpers below):
--   public.is_admin() reads the role from the JWT claim, NOT from the profiles
--   table. That is deliberate -- a table read here would recurse when called
--   from a policy on profiles itself, and would cost a query on every row check.
--   The consequence is that revoking someone's admin rights only reaches RLS at
--   their next token refresh (<= 1h). The API layer therefore re-reads
--   profiles.role from the database on every admin endpoint, so revocation is
--   immediate where it counts. RLS is the second line, not the only one.

create extension if not exists "pgcrypto";

create type public.user_role         as enum ('student', 'admin');
create type public.content_status    as enum ('draft', 'published', 'archived');
create type public.lesson_type       as enum ('video', 'text', 'quiz');
create type public.access_type       as enum ('lifetime', 'time_limited');
create type public.enrollment_status as enum ('active', 'refunded', 'expired');
create type public.enrollment_source as enum ('purchase', 'free', 'manual');
create type public.question_type     as enum ('single', 'multi', 'boolean', 'short_text');
create type public.payment_status    as enum ('pending', 'paid', 'refunded', 'disputed');
create type public.video_status      as enum ('absent', 'uploading', 'processing', 'ready', 'failed');

-- Keeps updated_at honest without trusting the application to set it.
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- Role as asserted by the current request's JWT. Defaults to the least
-- privilege on anything unexpected: no claim, malformed claim, or no session.
create or replace function public.jwt_role()
returns text language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'user_role',
    'student'
  );
$$;

create or replace function public.is_admin()
returns boolean language sql stable as $$
  select public.jwt_role() = 'admin';
$$;
