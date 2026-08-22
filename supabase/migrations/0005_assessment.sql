-- 0005_assessment: quizzes, questions, answer keys, attempts and responses.
--
-- The answer key (quiz_options.is_correct and quiz_questions.correct_answers)
-- is the single most sensitive thing in this database: a leak silently
-- invalidates every certificate ever issued, with no error to alert anyone.
-- It is protected twice -- the API never serialises those columns into a
-- student payload, and RLS (0008) denies anon/authenticated any access to them
-- at all. Neither layer is allowed to be the only one.

create table public.quizzes (
  id                uuid primary key default gen_random_uuid(),
  lesson_id         uuid not null unique references public.lessons (id) on delete cascade,
  title             text not null,
  description       text,
  passing_score     smallint not null default 70,
  -- null = unlimited (decision 3: no gating, so retries are unlimited by
  -- default). A cap is a config change, not a migration.
  max_attempts      smallint,
  time_limit_seconds integer,
  shuffle_questions boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  constraint quizzes_passing_score_range check (passing_score between 1 and 100),
  constraint quizzes_max_attempts_sane   check (max_attempts is null or max_attempts > 0),
  constraint quizzes_time_limit_sane     check (time_limit_seconds is null or time_limit_seconds >= 30)
);

create trigger quizzes_set_updated_at
  before update on public.quizzes
  for each row execute function public.set_updated_at();

create table public.quiz_questions (
  id              uuid primary key default gen_random_uuid(),
  quiz_id         uuid not null references public.quizzes (id) on delete cascade,
  type            public.question_type not null,
  prompt          text not null,
  explanation     text,
  points          smallint not null default 1,
  position        integer not null,
  -- Accepted answers for short_text questions. Part of the answer key: same
  -- protection as quiz_options.is_correct.
  correct_answers text[],
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  constraint quiz_questions_position_unique unique (quiz_id, position) deferrable initially deferred,
  constraint quiz_questions_points_positive check (points > 0),
  constraint quiz_questions_short_text_has_key
    check (type <> 'short_text' or (correct_answers is not null and cardinality(correct_answers) > 0))
);

create index quiz_questions_quiz_idx on public.quiz_questions (quiz_id, position);

create trigger quiz_questions_set_updated_at
  before update on public.quiz_questions
  for each row execute function public.set_updated_at();

create table public.quiz_options (
  id          uuid primary key default gen_random_uuid(),
  question_id uuid not null references public.quiz_questions (id) on delete cascade,
  text        text not null,
  is_correct  boolean not null default false,
  position    integer not null,
  created_at  timestamptz not null default now(),

  constraint quiz_options_position_unique unique (question_id, position) deferrable initially deferred
);

create index quiz_options_question_idx on public.quiz_options (question_id, position);

create table public.quiz_attempts (
  id                uuid primary key default gen_random_uuid(),
  quiz_id           uuid not null references public.quizzes (id) on delete cascade,
  user_id           uuid not null references public.profiles (id) on delete cascade,
  attempt_number    integer not null,
  started_at        timestamptz not null default now(),
  submitted_at      timestamptz,
  score             numeric(5,2),
  passed            boolean,
  time_spent_seconds integer,

  constraint quiz_attempts_unique unique (quiz_id, user_id, attempt_number),
  constraint quiz_attempts_number_positive check (attempt_number > 0),
  constraint quiz_attempts_score_range check (score is null or score between 0 and 100),
  -- A submitted attempt must be fully graded; an open one must be fully ungraded.
  constraint quiz_attempts_graded_together
    check ((submitted_at is null) = (score is null) and (submitted_at is null) = (passed is null))
);

create index quiz_attempts_user_idx on public.quiz_attempts (user_id, quiz_id);
create index quiz_attempts_passed_idx on public.quiz_attempts (user_id, quiz_id) where passed;

create table public.quiz_responses (
  id                 uuid primary key default gen_random_uuid(),
  attempt_id         uuid not null references public.quiz_attempts (id) on delete cascade,
  question_id        uuid not null references public.quiz_questions (id) on delete cascade,
  selected_option_ids uuid[] not null default '{}',
  text_answer        text,
  is_correct         boolean not null,
  points_awarded     numeric(6,2) not null default 0,

  constraint quiz_responses_unique unique (attempt_id, question_id)
);

create index quiz_responses_attempt_idx on public.quiz_responses (attempt_id);
