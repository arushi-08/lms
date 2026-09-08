-- 0011: assignments and their submissions.
--
-- An assignment is a lesson a student answers in their own words and an admin
-- marks by hand. Unlike a quiz it cannot be auto-graded, so it carries a review
-- workflow: submitted -> graded, with a score and written feedback.
--
-- v1 accepts written text and an optional link to work hosted elsewhere. File
-- upload needs Supabase Storage plus virus scanning and quota handling, which
-- is a larger piece than it looks; the column is here so adding it later is not
-- a migration of existing rows.

create type public.submission_status as enum ('submitted', 'graded', 'returned');

create table public.assignments (
  id             uuid primary key default gen_random_uuid(),
  lesson_id      uuid not null unique references public.lessons (id) on delete cascade,
  title          text not null,
  instructions   text not null,
  max_points     smallint not null default 100,
  passing_score  smallint not null default 70,
  -- Whether a passing grade is needed for the certificate. Some assignments
  -- are reflective exercises where submitting is the point.
  is_graded      boolean not null default true,
  allow_text     boolean not null default true,
  allow_link     boolean not null default false,
  -- null = no deadline. Past it, submission is refused unless late work is on.
  due_at         timestamptz,
  allow_late     boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),

  constraint assignments_points_positive  check (max_points > 0),
  constraint assignments_passing_in_range check (passing_score between 1 and 100),
  constraint assignments_accepts_something check (allow_text or allow_link)
);

create trigger assignments_set_updated_at
  before update on public.assignments
  for each row execute function public.set_updated_at();

create table public.assignment_submissions (
  id             uuid primary key default gen_random_uuid(),
  assignment_id  uuid not null references public.assignments (id) on delete cascade,
  user_id        uuid not null references public.profiles (id) on delete cascade,
  -- Resubmission keeps the earlier attempt rather than overwriting it: a
  -- student needs to see what the feedback referred to.
  attempt_number integer not null default 1,
  text_answer    text,
  link_url       text,
  -- Reserved for the Storage-backed upload; unused in v1.
  file_path      text,
  status         public.submission_status not null default 'submitted',
  submitted_at   timestamptz not null default now(),
  is_late        boolean not null default false,

  score          numeric(5,2),
  passed         boolean,
  feedback       text,
  graded_by      uuid references public.profiles (id) on delete set null,
  graded_at      timestamptz,

  constraint assignment_submissions_unique unique (assignment_id, user_id, attempt_number),
  constraint assignment_submissions_attempt_positive check (attempt_number > 0),
  constraint assignment_submissions_has_content
    check (coalesce(nullif(trim(text_answer), ''), link_url, file_path) is not null),
  constraint assignment_submissions_score_range
    check (score is null or score between 0 and 100),
  -- Graded means all of it: a score, a verdict and a timestamp, or none.
  constraint assignment_submissions_graded_together
    check ((status = 'graded') = (score is not null)
       and (status = 'graded') = (passed is not null)
       and (status = 'graded') = (graded_at is not null))
);

create index assignment_submissions_user_idx
  on public.assignment_submissions (user_id, assignment_id, attempt_number desc);
create index assignment_submissions_queue_idx
  on public.assignment_submissions (submitted_at) where status = 'submitted';

-- Resolves an assignment to its course, for entitlement checks in policies.
create or replace function public.assignment_course_id(p_assignment_id uuid)
returns uuid language sql stable security definer
set search_path = public, pg_temp as $$
  select m.course_id
  from public.assignments a
  join public.lessons l on l.id = a.lesson_id
  join public.modules m on m.id = l.module_id
  where a.id = p_assignment_id;
$$;

alter table public.assignments            enable row level security;
alter table public.assignment_submissions enable row level security;

-- Instructions are readable by anyone enrolled; the grading fields are not
-- separated because there is nothing secret in an assignment definition.
grant select on public.assignments to authenticated;

create policy assignments_read_enrolled on public.assignments
  for select to authenticated
  using (public.has_active_enrollment(public.lesson_course_id(lesson_id)));
create policy assignments_read_admin on public.assignments
  for select to authenticated using (public.is_admin());

-- Read-only to the owner. Submitting and grading both go through the API:
-- a student who could UPDATE this could grade their own work.
grant select on public.assignment_submissions to authenticated;

create policy assignment_submissions_read_own on public.assignment_submissions
  for select to authenticated using (user_id = auth.uid());
create policy assignment_submissions_read_admin on public.assignment_submissions
  for select to authenticated using (public.is_admin());
