-- 0004_enrollment: enrolments and per-lesson progress.

create table public.enrollments (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references public.profiles (id) on delete cascade,
  course_id        uuid not null references public.courses (id) on delete cascade,
  status           public.enrollment_status not null default 'active',
  source           public.enrollment_source not null,
  progress_percent numeric(5,2) not null default 0,
  last_lesson_id   uuid references public.lessons (id) on delete set null,
  -- Snapshotted at enrolment from the course's access policy. Storing the
  -- resolved instant rather than recomputing from courses.access_days means
  -- changing a course's policy later can never retroactively revoke access
  -- somebody already paid for.
  expires_at       timestamptz,
  enrolled_at      timestamptz not null default now(),
  completed_at     timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint enrollments_unique unique (user_id, course_id),
  constraint enrollments_progress_range check (progress_percent between 0 and 100)
);

create index enrollments_user_idx   on public.enrollments (user_id, status);
create index enrollments_course_idx on public.enrollments (course_id);

create trigger enrollments_set_updated_at
  before update on public.enrollments
  for each row execute function public.set_updated_at();

-- Single source of truth for "may this user see paid content in this course".
-- security definer so entitlement checks in policies on other tables do not
-- depend on the caller's visibility of enrollments.
create or replace function public.has_active_enrollment(p_course_id uuid)
returns boolean language sql stable security definer
set search_path = public, pg_temp as $$
  select exists (
    select 1
    from public.enrollments e
    where e.user_id    = auth.uid()
      and e.course_id  = p_course_id
      and e.status     = 'active'
      and (e.expires_at is null or e.expires_at > now())
  );
$$;

create table public.lesson_progress (
  id                    uuid primary key default gen_random_uuid(),
  user_id               uuid not null references public.profiles (id) on delete cascade,
  lesson_id             uuid not null references public.lessons (id) on delete cascade,
  enrollment_id         uuid not null references public.enrollments (id) on delete cascade,
  watched_seconds       integer not null default 0,
  last_position_seconds integer not null default 0,
  completed             boolean not null default false,
  completed_at          timestamptz,
  -- Anchor for server-side clamping: a heartbeat may never credit more watched
  -- time than has actually elapsed on the wall clock since the previous one.
  last_heartbeat_at     timestamptz,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),

  constraint lesson_progress_unique unique (user_id, lesson_id),
  constraint lesson_progress_non_negative
    check (watched_seconds >= 0 and last_position_seconds >= 0),
  constraint lesson_progress_completed_has_date
    check (not completed or completed_at is not null)
);

create index lesson_progress_user_idx       on public.lesson_progress (user_id, lesson_id);
create index lesson_progress_enrollment_idx on public.lesson_progress (enrollment_id) where completed;

create trigger lesson_progress_set_updated_at
  before update on public.lesson_progress
  for each row execute function public.set_updated_at();
