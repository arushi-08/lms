-- 0009_seed_dev: development seed. Safe to run repeatedly.
--
-- Deliberately contains NO users. Accounts are created through Supabase Auth so
-- that password hashing and email verification take the real path; promoting
-- the first admin is a documented one-liner in lms/README.md rather than a
-- seeded backdoor that could reach production.
--
-- Idempotency uses `where not exists` rather than `on conflict do nothing`,
-- because the position uniqueness constraints are deferrable and Postgres will
-- not accept a deferrable constraint as an ON CONFLICT arbiter.

insert into public.courses (
  slug, title, subtitle, description, status, access_type,
  is_free, price_cents, currency, completion_threshold, published_at
)
select
  'pilot-course',
  'Pilot Course',
  'A sample course used to exercise the platform end to end',
  'Placeholder course for pilot testing. Replace once real content is ready.',
  'published', 'lifetime',
  true, 0, 'USD', 90, now()
where not exists (select 1 from public.courses where slug = 'pilot-course');

insert into public.modules (course_id, title, description, position)
select c.id, v.title, v.description, v.position
from public.courses c
cross join (values
  ('Getting Started', 'Orientation and setup',        1),
  ('Core Concepts',   'The main body of the course',  2)
) as v(title, description, position)
where c.slug = 'pilot-course'
  and not exists (
    select 1 from public.modules m
    where m.course_id = c.id and m.position = v.position
  );

-- Six lessons across two modules: five video (matching the 4-5 sample clips
-- planned for testing) and one quiz.
insert into public.lessons (module_id, title, slug, type, position, is_preview, is_required)
select m.id, v.title, v.slug, v.type::public.lesson_type, v.position, v.is_preview, true
from public.modules m
join public.courses c on c.id = m.course_id
cross join (values
  (1, 'Welcome',            'welcome',         'video', 1, true),
  (1, 'How This Works',     'how-it-works',    'video', 2, false),
  (1, 'Your First Concept', 'first-concept',   'video', 3, false),
  (2, 'Going Deeper',       'going-deeper',    'video', 1, false),
  (2, 'Worked Example',     'worked-example',  'video', 2, false),
  (2, 'Knowledge Check',    'knowledge-check', 'quiz',  3, false)
) as v(module_position, title, slug, type, position, is_preview)
where c.slug = 'pilot-course'
  and m.position = v.module_position
  and not exists (
    select 1 from public.lessons l
    where l.module_id = m.id and l.position = v.position
  );

-- A quiz on the Knowledge Check lesson, so grading has something to grade.
insert into public.quizzes (lesson_id, title, passing_score)
select l.id, 'Knowledge Check', 70
from public.lessons l
join public.modules m on m.id = l.module_id
join public.courses c on c.id = m.course_id
where c.slug = 'pilot-course' and l.slug = 'knowledge-check'
  and not exists (select 1 from public.quizzes q where q.lesson_id = l.id);

insert into public.quiz_questions (quiz_id, type, prompt, explanation, points, position, correct_answers)
select q.id, v.type::public.question_type, v.prompt, v.explanation, 1, v.position, v.correct_answers
from public.quizzes q
join public.lessons l on l.id = q.lesson_id
cross join (values
  ('single', 'Which statement best describes the core idea?',
   'Covered in Going Deeper.', 1, null::text[]),
  ('multi',  'Select all techniques introduced in this module.',
   'Two of the four were introduced.', 2, null::text[]),
  ('boolean','The technique applies to every situation.',
   'It does not -- see the caveats section.', 3, null::text[]),
  ('short_text', 'Name the model introduced in lesson two.',
   'Case and surrounding whitespace are ignored when grading.',
   4, array['worked example', 'the worked example'])
) as v(type, prompt, explanation, position, correct_answers)
where l.slug = 'knowledge-check'
  and not exists (
    select 1 from public.quiz_questions qq
    where qq.quiz_id = q.id and qq.position = v.position
  );

insert into public.quiz_options (question_id, text, is_correct, position)
select qq.id, v.text, v.is_correct, v.position
from public.quiz_questions qq
join public.quizzes q on q.id = qq.quiz_id
join public.lessons l on l.id = q.lesson_id
cross join lateral (values
  (qq.position, 'The first option',  qq.position = 1, 1),
  (qq.position, 'The second option', qq.position = 2, 2),
  (qq.position, 'The third option',  false,           3)
) as v(qpos, text, is_correct, position)
where l.slug = 'knowledge-check'
  and qq.type in ('single', 'multi')
  and not exists (
    select 1 from public.quiz_options qo
    where qo.question_id = qq.id and qo.position = v.position
  );

insert into public.quiz_options (question_id, text, is_correct, position)
select qq.id, v.text, v.is_correct, v.position
from public.quiz_questions qq
join public.quizzes q on q.id = qq.quiz_id
join public.lessons l on l.id = q.lesson_id
cross join (values
  ('True',  false, 1),
  ('False', true,  2)
) as v(text, is_correct, position)
where l.slug = 'knowledge-check'
  and qq.type = 'boolean'
  and not exists (
    select 1 from public.quiz_options qo
    where qo.question_id = qq.id and qo.position = v.position
  );
