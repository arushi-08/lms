-- 0014_youtube_lessons: lessons whose video lives on YouTube.
--
-- Until now the video provider was one environment variable for the whole
-- deployment, because there was one provider. There are now two at once:
-- VdoCipher for protected course content, and YouTube for clips that are
-- already public. Which one a lesson uses is therefore a property of the
-- lesson, not of the deployment.
--
-- What this does NOT do is pretend a YouTube lesson is protected. A YouTube
-- video is retrievable by anyone holding its id -- unlisted is not private --
-- so there is no OTP to mint, no watermark to burn in and no concurrent-stream
-- cap worth enforcing on it. The application drops all three for these lessons
-- rather than performing them; see app/routers/video.py. Entitlement is
-- unchanged: a YouTube lesson inside a gated course is still gated, and the way
-- to open one up is the `is_preview` flag that already exists.

create type public.video_source as enum ('managed', 'youtube');

alter table public.lessons
  --: 'managed' means the configured provider owns the file (VdoCipher, or the
  --: mock in development) and video_id is that provider's id. 'youtube' means
  --: video_id is an 11-character YouTube id and nothing was uploaded here.
  add column video_source public.video_source not null default 'managed';

comment on column public.lessons.video_source is
  'Who holds the bytes. Managed video is protected and gated; YouTube video is '
  'public wherever it is embedded, and is presented by this platform rather '
  'than protected by it.';

-- The id is interpolated into an iframe URL, so its shape is constrained here
-- as well as in the API. Defence in depth is the whole reason the API is not
-- the only thing standing between a crafted string and a rendered page, and an
-- admin account is exactly the account an attacker would be using.
alter table public.lessons
  add constraint lessons_youtube_id_shape check (
    video_source <> 'youtube'
    or (video_id is not null and video_id ~ '^[A-Za-z0-9_-]{11}$')
  );

-- Nothing uploads a YouTube video, so it is never 'uploading' or 'processing':
-- it is playable the moment the id is saved. Letting it sit in another state
-- would strand the lesson behind the "video is not ready yet" check forever.
alter table public.lessons
  add constraint lessons_youtube_is_ready check (
    video_source <> 'youtube' or video_status = 'ready'
  );

create index lessons_video_source_idx
  on public.lessons (video_source) where video_source <> 'managed';
