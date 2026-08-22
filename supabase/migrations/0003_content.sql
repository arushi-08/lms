-- 0003_content: course > module > lesson.

create table public.courses (
  id                   uuid primary key default gen_random_uuid(),
  slug                 text not null unique,
  title                text not null,
  subtitle             text,
  description          text,
  thumbnail_url        text,
  status               public.content_status not null default 'draft',
  -- Access policy lives per course (decision 1): the first course is lifetime,
  -- later courses may be time limited without a migration.
  access_type          public.access_type not null default 'lifetime',
  access_days          integer,
  is_free              boolean not null default true,
  price_cents          integer not null default 0,
  currency             char(3) not null default 'USD',
  -- Tax is a separate component, never folded into price_cents, so an 18% GST
  -- change is a config edit rather than a reprice of every course.
  tax_rate_bps         integer not null default 0,
  provider_price_ref   text,
  -- Percent of a video that counts as watched. Per course so a dense lecture
  -- can demand 95% while a casual intro accepts 80%.
  completion_threshold smallint not null default 90,
  published_at         timestamptz,
  created_by           uuid references public.profiles (id) on delete set null,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),

  constraint courses_access_days_required
    check (access_type = 'lifetime' or (access_days is not null and access_days > 0)),
  constraint courses_price_non_negative check (price_cents >= 0),
  constraint courses_free_is_zero_price  check (not is_free or price_cents = 0),
  constraint courses_tax_sane            check (tax_rate_bps between 0 and 10000),
  constraint courses_threshold_sane      check (completion_threshold between 1 and 100),
  constraint courses_published_has_date
    check (status <> 'published' or published_at is not null)
);

create index courses_status_idx on public.courses (status) where status = 'published';

create trigger courses_set_updated_at
  before update on public.courses
  for each row execute function public.set_updated_at();

create table public.modules (
  id          uuid primary key default gen_random_uuid(),
  course_id   uuid not null references public.courses (id) on delete cascade,
  title       text not null,
  description text,
  position    integer not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  -- Deferrable so a drag-and-drop reorder can shuffle positions inside one
  -- transaction without tripping over itself mid-update.
  constraint modules_position_unique unique (course_id, position) deferrable initially deferred,
  constraint modules_position_positive check (position > 0)
);

create index modules_course_idx on public.modules (course_id, position);

create trigger modules_set_updated_at
  before update on public.modules
  for each row execute function public.set_updated_at();

create table public.lessons (
  id               uuid primary key default gen_random_uuid(),
  module_id        uuid not null references public.modules (id) on delete cascade,
  title            text not null,
  slug             text not null,
  type             public.lesson_type not null,
  position         integer not null,
  is_preview       boolean not null default false,
  is_required      boolean not null default true,
  duration_seconds integer,
  content          jsonb,
  video_id         text,
  video_status     public.video_status not null default 'absent',
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  constraint lessons_position_unique unique (module_id, position) deferrable initially deferred,
  constraint lessons_slug_unique     unique (module_id, slug),
  constraint lessons_position_positive check (position > 0),
  constraint lessons_video_has_id
    check (type <> 'video' or video_status = 'absent' or video_id is not null)
);

create index lessons_module_idx on public.lessons (module_id, position);
create index lessons_video_idx  on public.lessons (video_id) where video_id is not null;

create trigger lessons_set_updated_at
  before update on public.lessons
  for each row execute function public.set_updated_at();

-- Resolves a lesson to its course in one hop. Used by entitlement checks in
-- policies, so it is security definer and marked stable for the planner.
create or replace function public.lesson_course_id(p_lesson_id uuid)
returns uuid language sql stable security definer
set search_path = public, pg_temp as $$
  select m.course_id
  from public.lessons l
  join public.modules m on m.id = l.module_id
  where l.id = p_lesson_id;
$$;
