-- 0007_operational: audit trail, playback ledger, notifications.

-- Every OTP issued, so a watermarked leak can be traced to an account and a
-- session, and so concurrent-stream abuse is visible.
create table public.video_playback_sessions (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.profiles (id) on delete cascade,
  lesson_id  uuid not null references public.lessons (id) on delete cascade,
  issued_at  timestamptz not null default now(),
  expires_at timestamptz not null,
  ip         inet,
  user_agent text
);

create index video_playback_active_idx
  on public.video_playback_sessions (user_id, expires_at desc);
create index video_playback_lesson_idx
  on public.video_playback_sessions (lesson_id, issued_at desc);

-- Insert-only. No role is granted update or delete (see 0008): an audit log
-- that can be edited is a log, not an audit.
create table public.audit_log (
  id          bigint generated always as identity primary key,
  actor_id    uuid references public.profiles (id) on delete set null,
  action      text not null,
  entity_type text not null,
  entity_id   text,
  diff        jsonb,
  ip          inet,
  created_at  timestamptz not null default now()
);

create index audit_log_actor_idx  on public.audit_log (actor_id, created_at desc);
create index audit_log_entity_idx on public.audit_log (entity_type, entity_id, created_at desc);

create table public.notifications (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references public.profiles (id) on delete cascade,
  type       text not null,
  title      text not null,
  body       text,
  link       text,
  read_at    timestamptz,
  created_at timestamptz not null default now()
);

create index notifications_user_idx on public.notifications (user_id, created_at desc);
create index notifications_unread_idx on public.notifications (user_id) where read_at is null;
