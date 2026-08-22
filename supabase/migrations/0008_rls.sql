-- 0008_rls: row level security and column grants.
--
-- Posture: deny by default, everywhere. Supabase's stock configuration grants
-- anon and authenticated broad table privileges, so step one is taking those
-- back and re-granting only what the browser genuinely needs.
--
-- The browser reads catalog and its own records directly through PostgREST.
-- Everything else -- writes, the answer key, money, audit -- is reachable only
-- with the service_role key, which lives on the API server and nowhere else.

revoke all on all tables in schema public from anon, authenticated;
alter default privileges in schema public revoke all on tables from anon, authenticated;

-- Helpers used by the policies below. security definer so a policy on one table
-- does not depend on the caller's visibility of another.
create or replace function public.course_is_published(p_course_id uuid)
returns boolean language sql stable security definer
set search_path = public, pg_temp as $$
  select exists (
    select 1 from public.courses c
    where c.id = p_course_id and c.status = 'published'
  );
$$;

create or replace function public.module_course_id(p_module_id uuid)
returns uuid language sql stable security definer
set search_path = public, pg_temp as $$
  select m.course_id from public.modules m where m.id = p_module_id;
$$;

create or replace function public.quiz_course_id(p_quiz_id uuid)
returns uuid language sql stable security definer
set search_path = public, pg_temp as $$
  select m.course_id
  from public.quizzes q
  join public.lessons l on l.id = q.lesson_id
  join public.modules m on m.id = l.module_id
  where q.id = p_quiz_id;
$$;

alter table public.profiles                enable row level security;
alter table public.courses                 enable row level security;
alter table public.modules                 enable row level security;
alter table public.lessons                 enable row level security;
alter table public.enrollments             enable row level security;
alter table public.lesson_progress         enable row level security;
alter table public.quizzes                 enable row level security;
alter table public.quiz_questions          enable row level security;
alter table public.quiz_options            enable row level security;
alter table public.quiz_attempts           enable row level security;
alter table public.quiz_responses          enable row level security;
alter table public.certificates            enable row level security;
alter table public.payments                enable row level security;
alter table public.provider_events         enable row level security;
alter table public.video_playback_sessions enable row level security;
alter table public.audit_log               enable row level security;
alter table public.notifications           enable row level security;

-- ---------------------------------------------------------------- profiles --
-- Readable: your own row, or any row if you are an admin.
-- Writable: your own display fields only. role is not in the column grant, so
-- a student cannot promote themselves even with a crafted PATCH.
grant select (id, email, full_name, avatar_url, role, created_at) on public.profiles to authenticated;
grant update (full_name, avatar_url) on public.profiles to authenticated;

create policy profiles_read_own on public.profiles
  for select to authenticated using (id = auth.uid());
create policy profiles_read_admin on public.profiles
  for select to authenticated using (public.is_admin());
create policy profiles_update_own on public.profiles
  for update to authenticated using (id = auth.uid()) with check (id = auth.uid());

-- ----------------------------------------------------------------- courses --
grant select on public.courses to anon, authenticated;

create policy courses_read_published on public.courses
  for select to anon, authenticated using (status = 'published');
create policy courses_read_admin on public.courses
  for select to authenticated using (public.is_admin());

-- ----------------------------------------------------------------- modules --
grant select on public.modules to anon, authenticated;

create policy modules_read_published on public.modules
  for select to anon, authenticated using (public.course_is_published(course_id));
create policy modules_read_admin on public.modules
  for select to authenticated using (public.is_admin());

-- ----------------------------------------------------------------- lessons --
-- Column-level grant, not a row-level one. The curriculum is browsable before
-- purchase -- titles, ordering, durations, which lessons are free previews --
-- but `content` and `video_id` are simply not granted to anon or authenticated
-- at all. Those two columns are readable only with the service_role key, after
-- the API has checked entitlement. There is no policy to get wrong.
grant select (
  id, module_id, title, slug, type, position,
  is_preview, is_required, duration_seconds, video_status, created_at, updated_at
) on public.lessons to anon, authenticated;

create policy lessons_read_published on public.lessons
  for select to anon, authenticated
  using (public.course_is_published(public.module_course_id(module_id)));
create policy lessons_read_admin on public.lessons
  for select to authenticated using (public.is_admin());

-- ------------------------------------------------------------- enrollments --
-- Read-only to the owner. Every write goes through the API, because enrolment
-- is an entitlement grant and students do not get to grant themselves those.
grant select on public.enrollments to authenticated;

create policy enrollments_read_own on public.enrollments
  for select to authenticated using (user_id = auth.uid());
create policy enrollments_read_admin on public.enrollments
  for select to authenticated using (public.is_admin());

-- --------------------------------------------------------- lesson_progress --
-- Also read-only: progress is written by the API so it can be clamped against
-- the wall clock. A student who could UPDATE this directly could award
-- themselves a certificate in one request.
grant select on public.lesson_progress to authenticated;

create policy lesson_progress_read_own on public.lesson_progress
  for select to authenticated using (user_id = auth.uid());
create policy lesson_progress_read_admin on public.lesson_progress
  for select to authenticated using (public.is_admin());

-- ----------------------------------------------------------------- quizzes --
grant select on public.quizzes to authenticated;

create policy quizzes_read_enrolled on public.quizzes
  for select to authenticated
  using (public.has_active_enrollment(public.lesson_course_id(lesson_id)));
create policy quizzes_read_admin on public.quizzes
  for select to authenticated using (public.is_admin());

-- ---------------------------------------------------------- quiz_questions --
-- correct_answers is excluded from the grant: part of the answer key.
grant select (id, quiz_id, type, prompt, points, position) on public.quiz_questions to authenticated;

create policy quiz_questions_read_enrolled on public.quiz_questions
  for select to authenticated
  using (public.has_active_enrollment(public.quiz_course_id(quiz_id)));
create policy quiz_questions_read_admin on public.quiz_questions
  for select to authenticated using (public.is_admin());

-- ------------------------------------------------------------ quiz_options --
-- No grant of any kind to anon or authenticated. Not the text, not the
-- ordering, and above all not is_correct. The API assembles the student's
-- question payload with the key stripped; this table is invisible to the
-- browser's credentials no matter what query it sends.
-- (Intentionally no policies: with no grant, policies would be decoration.)

-- ----------------------------------------------------------- quiz_attempts --
grant select on public.quiz_attempts to authenticated;

create policy quiz_attempts_read_own on public.quiz_attempts
  for select to authenticated using (user_id = auth.uid());
create policy quiz_attempts_read_admin on public.quiz_attempts
  for select to authenticated using (public.is_admin());

-- ---------------------------------------------------------- quiz_responses --
grant select on public.quiz_responses to authenticated;

create policy quiz_responses_read_own on public.quiz_responses
  for select to authenticated
  using (exists (
    select 1 from public.quiz_attempts a
    where a.id = attempt_id and a.user_id = auth.uid()
  ));
create policy quiz_responses_read_admin on public.quiz_responses
  for select to authenticated using (public.is_admin());

-- ------------------------------------------------------------ certificates --
-- Owners see their own. Public verification deliberately does NOT go through
-- anon RLS -- it is an API route, so verification can be rate limited and the
-- serial cannot be enumerated with a PostgREST range query.
grant select on public.certificates to authenticated;

create policy certificates_read_own on public.certificates
  for select to authenticated using (user_id = auth.uid());
create policy certificates_read_admin on public.certificates
  for select to authenticated using (public.is_admin());

-- ----------------------------------------------------------- notifications --
grant select on public.notifications to authenticated;
grant update (read_at) on public.notifications to authenticated;

create policy notifications_read_own on public.notifications
  for select to authenticated using (user_id = auth.uid());
create policy notifications_mark_read on public.notifications
  for update to authenticated using (user_id = auth.uid()) with check (user_id = auth.uid());

-- -------------------------------------- payments, events, audit, playback --
-- No grants and no policies. Money, provider payloads, the audit trail and the
-- playback ledger are service_role only; even the admin panel reaches them
-- through the API, so there is one enforcement path to review rather than two.
-- audit_log additionally never receives update or delete from any role: a log
-- that can be edited is not an audit.
