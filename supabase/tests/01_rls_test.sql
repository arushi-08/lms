-- 01_rls_test: adversarial tests against the row level security policies.
--
-- Every check here is phrased as an attack a signed-in student could actually
-- attempt with the public anon key and their own JWT -- reading the answer key,
-- reading another student's records, promoting themselves to admin, granting
-- themselves an enrolment. A policy nobody has tried to break is a guess.
--
-- Run: psql -v ON_ERROR_STOP=1 -f 00_shim_supabase.sql -f <migrations> -f 01_rls_test.sql

create schema if not exists tests;
grant usage on schema tests to public;

drop table if exists tests.results;
create table tests.results (label text, ok boolean);
grant all on tests.results to public;

-- Runs a statement and reports whether the database refused it. Security
-- invoker, so it executes with the privileges of whoever is currently SET ROLE.
create or replace function tests.is_denied(stmt text)
returns boolean language plpgsql as $$
begin
  execute stmt;
  return false;
exception
  -- Deliberately narrow: only a real privilege refusal counts as "denied".
  -- Catching undefined_table/undefined_column here would let a typo'd table
  -- name pass as a successful security check, which is worse than no test.
  when insufficient_privilege then return true;
end;
$$;

create or replace function tests.rowcount(stmt text)
returns bigint language plpgsql as $$
declare n bigint;
begin
  execute 'select count(*) from (' || stmt || ') _t' into n;
  return n;
end;
$$;

create or replace function tests.check(label text, ok boolean)
returns void language sql as $$
  insert into tests.results values (label, ok);
$$;

create or replace function tests.act_as(p_user uuid, p_role text)
returns void language sql as $$
  select set_config(
    'request.jwt.claims',
    json_build_object('sub', p_user::text, 'user_role', p_role)::text,
    false
  );
$$;

-- ------------------------------------------------------------------ set-up --
insert into auth.users (id, email, raw_user_meta_data) values
  ('11111111-1111-1111-1111-111111111111', 'alice@example.test', '{"full_name":"Alice Enrolled"}'),
  ('22222222-2222-2222-2222-222222222222', 'bob@example.test',   '{"full_name":"Bob Outsider"}'),
  ('33333333-3333-3333-3333-333333333333', 'admin@example.test', '{"full_name":"Admin User"}');

update public.profiles set role = 'admin'
  where id = '33333333-3333-3333-3333-333333333333';

-- Alice is enrolled in the seeded pilot course; Bob is not.
insert into public.enrollments (user_id, course_id, source)
select '11111111-1111-1111-1111-111111111111', id, 'free'
from public.courses where slug = 'pilot-course';

-- An unpublished course, to prove drafts stay invisible.
insert into public.courses (slug, title, status, access_type, is_free, currency)
values ('secret-draft', 'Unreleased Course', 'draft', 'lifetime', true, 'USD');

insert into public.modules (course_id, title, position)
select id, 'Hidden Module', 1 from public.courses where slug = 'secret-draft';

-- A graded attempt for Alice, so quiz_responses has something to protect.
insert into public.quiz_attempts (quiz_id, user_id, attempt_number, submitted_at, score, passed)
select q.id, '11111111-1111-1111-1111-111111111111', 1, now(), 100, true
from public.quizzes q limit 1;

insert into public.quiz_responses (attempt_id, question_id, is_correct, points_awarded)
select a.id, qq.id, true, 1
from public.quiz_attempts a
join public.quiz_questions qq on qq.quiz_id = a.quiz_id
limit 1;

insert into public.notifications (user_id, type, title) values
  ('11111111-1111-1111-1111-111111111111', 'welcome', 'Welcome Alice'),
  ('22222222-2222-2222-2222-222222222222', 'welcome', 'Welcome Bob');

-- Give the video lessons real content, so "cannot read it" means something.
update public.lessons
set video_id = 'vdo-secret-' || position, video_status = 'ready'
where type = 'video';

-- ----------------------------------------------------------- anon: catalog --
set role anon;
select set_config('request.jwt.claims', '', false);

select tests.check('anon sees published course',
  tests.rowcount('select 1 from courses where slug = ''pilot-course''') = 1);
select tests.check('anon CANNOT see draft course',
  tests.rowcount('select 1 from courses where slug = ''secret-draft''') = 0);
select tests.check('anon CAN browse modules of a published course',
  tests.rowcount('select 1 from modules') = 2);
select tests.check('anon CANNOT see modules of a draft course',
  tests.rowcount(
    'select 1 from modules where title = ''Hidden Module''') = 0);
select tests.check('anon CANNOT read lessons.video_id',
  tests.is_denied('select video_id from lessons'));
select tests.check('anon CANNOT read quiz_options',
  tests.is_denied('select * from quiz_options'));
reset role;

-- ------------------------------------------- bob: signed in, NOT enrolled --
set role authenticated;
select tests.act_as('22222222-2222-2222-2222-222222222222', 'student');

select tests.check('non-enrolled student CAN browse curriculum metadata',
  tests.rowcount('select 1 from lessons') = 6);
select tests.check('non-enrolled student CANNOT read lessons.content',
  tests.is_denied('select content from lessons'));
select tests.check('non-enrolled student CANNOT read lessons.video_id',
  tests.is_denied('select video_id from lessons'));
select tests.check('non-enrolled student CANNOT read quiz_options (answer key)',
  tests.is_denied('select * from quiz_options'));
select tests.check('non-enrolled student CANNOT read correct_answers (answer key)',
  tests.is_denied('select correct_answers from quiz_questions'));
select tests.check('non-enrolled student sees NO quizzes',
  tests.rowcount('select 1 from quizzes') = 0);
select tests.check('non-enrolled student sees NO quiz questions',
  tests.rowcount('select 1 from quiz_questions') = 0);
select tests.check('has_active_enrollment false for non-enrolled',
  (select not public.has_active_enrollment(id) from courses where slug = 'pilot-course'));
select tests.check('student sees only own notifications',
  tests.rowcount('select 1 from notifications') = 1);
select tests.check('student CANNOT see another student''s notifications',
  tests.rowcount('select 1 from notifications where title = ''Welcome Alice''') = 0);
select tests.check('student with no attempts sees no quiz responses',
  tests.rowcount('select 1 from quiz_responses') = 0);
select tests.check('student CANNOT see another student''s attempts',
  tests.rowcount('select 1 from quiz_attempts') = 0);

-- ------------------------------------------------- alice: signed in, enrolled --
select tests.act_as('11111111-1111-1111-1111-111111111111', 'student');

select tests.check('enrolled student sees own enrolment',
  tests.rowcount('select 1 from enrollments') = 1);
select tests.check('enrolled student CAN see quizzes',
  tests.rowcount('select 1 from quizzes') = 1);
select tests.check('enrolled student CAN see quiz questions',
  tests.rowcount('select 1 from quiz_questions') = 4);
select tests.check('enrolled student STILL cannot read the answer key',
  tests.is_denied('select * from quiz_options'));
select tests.check('enrolled student STILL cannot read video_id',
  tests.is_denied('select video_id from lessons'));
select tests.check('has_active_enrollment true for enrolled',
  (select public.has_active_enrollment(id) from courses where slug = 'pilot-course'));
select tests.check('student sees own quiz attempt',
  tests.rowcount('select 1 from quiz_attempts') = 1);
select tests.check('student sees own quiz responses',
  tests.rowcount('select 1 from quiz_responses') = 1);
select tests.check('student CAN mark own notification read',
  not tests.is_denied(
    'update notifications set read_at = now() where user_id = auth.uid()'));
select tests.check('student CANNOT edit notification content',
  tests.is_denied('update notifications set title = ''hacked'''));

-- -------------------------------------------------- cross-tenant isolation --
select tests.check('student sees only own profile',
  tests.rowcount('select 1 from profiles') = 1);
select tests.check('student CANNOT see another student''s profile',
  tests.rowcount('select 1 from profiles where email = ''bob@example.test''') = 0);

-- ------------------------------------------------------ privilege escalation --
select tests.check('student CANNOT promote self to admin',
  tests.is_denied('update profiles set role = ''admin'' where id = auth.uid()'));
select tests.check('student CAN edit own display name',
  not tests.is_denied('update profiles set full_name = ''Renamed'' where id = auth.uid()'));
select tests.check('student CANNOT grant self an enrolment',
  tests.is_denied(
    'insert into enrollments (user_id, course_id, source) '
    || 'select auth.uid(), id, ''free'' from courses where slug = ''secret-draft'''));
select tests.check('student CANNOT forge progress',
  tests.is_denied('update lesson_progress set completed = true, watched_seconds = 99999'));
select tests.check('student CANNOT forge a passing attempt',
  tests.is_denied('update quiz_attempts set passed = true, score = 100'));
select tests.check('student CANNOT issue self a certificate',
  tests.is_denied(
    'insert into certificates (serial, user_id, course_id, student_name_snapshot, course_title_snapshot) '
    || 'select ''FORGED'', auth.uid(), id, ''Alice'', ''Pilot'' from courses limit 1'));

-- -------------------------------------------------------- operational data --
select tests.check('student CANNOT read payments',   tests.is_denied('select * from payments'));
select tests.check('student CANNOT read audit_log',  tests.is_denied('select * from audit_log'));
select tests.check('student CANNOT read provider_events',
  tests.is_denied('select * from provider_events'));
select tests.check('student CANNOT read playback ledger',
  tests.is_denied('select * from video_playback_sessions'));
select tests.check('student CANNOT tamper with audit_log',
  tests.is_denied('insert into audit_log (action, entity_type) values (''forged'', ''x'')'));

-- --------------------------------------------------------- expired access --
reset role;
update public.enrollments
set expires_at = now() - interval '1 day'
where user_id = '11111111-1111-1111-1111-111111111111';

set role authenticated;
select tests.act_as('11111111-1111-1111-1111-111111111111', 'student');
select tests.check('expired enrolment loses entitlement',
  (select not public.has_active_enrollment(id) from courses where slug = 'pilot-course'));
select tests.check('expired enrolment loses quiz access',
  tests.rowcount('select 1 from quizzes') = 0);

reset role;
update public.enrollments set expires_at = null
where user_id = '11111111-1111-1111-1111-111111111111';

-- --------------------------------------------------------------- admin role --
set role authenticated;
select tests.act_as('33333333-3333-3333-3333-333333333333', 'admin');

select tests.check('admin sees all profiles',
  tests.rowcount('select 1 from profiles') = 3);
select tests.check('admin sees draft courses',
  tests.rowcount('select 1 from courses where slug = ''secret-draft''') = 1);
select tests.check('admin sees all enrolments',
  tests.rowcount('select 1 from enrollments') = 1);
-- Even an admin JWT does not unlock the answer key over PostgREST: admin tools
-- go through the API, which uses service_role. One enforcement path, not two.
select tests.check('admin JWT still cannot read answer key via PostgREST',
  tests.is_denied('select * from quiz_options'));

-- A forged claim is worthless without a signature Supabase will accept, but
-- verify the blast radius anyway: claiming admin must not unlock the key.
select tests.act_as('22222222-2222-2222-2222-222222222222', 'admin');
select tests.check('forged admin claim still cannot read answer key',
  tests.is_denied('select * from quiz_options'));

reset role;

-- ------------------------------------------------------------------ report --
select label, case when ok then 'PASS' else 'FAIL' end as result
from tests.results order by ok, label;

do $$
declare failed int;
begin
  select count(*) into failed from tests.results where not ok;
  raise notice '% checks, % failed', (select count(*) from tests.results), failed;
  if failed > 0 then
    raise exception 'RLS test suite failed: % check(s)', failed;
  end if;
end;
$$;
