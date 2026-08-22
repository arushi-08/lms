-- 0006: certificates, and the payment tables that ship now but stay unused
-- until Stripe (or a replacement) is approved.

create table public.certificates (
  id                    uuid primary key default gen_random_uuid(),
  -- Public verification code. Separate from the primary key so the id can stay
  -- an internal detail and the printed code can be rotated if it ever leaks.
  serial                text not null unique,
  user_id               uuid not null references public.profiles (id) on delete cascade,
  course_id             uuid not null references public.courses (id) on delete cascade,
  -- Snapshots, not joins. A certificate is a statement about a moment; editing
  -- a profile name or a course title later must not silently rewrite history
  -- on an already-issued document.
  student_name_snapshot text not null,
  course_title_snapshot text not null,
  issued_at             timestamptz not null default now(),
  pdf_path              text,
  -- Refunds revoke certificates (decision 4). Kept as a timestamp rather than
  -- a delete so /verify can say "revoked" instead of 404 -- a vanished
  -- certificate reads as a broken link, not as a revocation.
  revoked_at            timestamptz,
  revoked_reason        text,

  constraint certificates_unique unique (user_id, course_id)
);

create index certificates_serial_idx on public.certificates (serial);
create index certificates_user_idx   on public.certificates (user_id);

create table public.payments (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.profiles (id) on delete cascade,
  course_id          uuid not null references public.courses (id) on delete restrict,
  -- Provider-agnostic by design: the pilot has no approved provider, and the
  -- India question (PLAN.md 1.G-IN) may yet make it Razorpay rather than Stripe.
  provider           text not null,
  provider_session_id text unique,
  provider_payment_id text,
  amount_cents       integer not null,
  tax_cents          integer not null default 0,
  currency           char(3) not null,
  status             public.payment_status not null default 'pending',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  refunded_at        timestamptz,

  constraint payments_amount_non_negative check (amount_cents >= 0 and tax_cents >= 0)
);

create index payments_user_idx on public.payments (user_id);

create trigger payments_set_updated_at
  before update on public.payments
  for each row execute function public.set_updated_at();

-- Inserting the provider's event id IS the idempotency lock: a redelivered
-- webhook hits the primary key conflict and exits without double-enrolling.
create table public.provider_events (
  id           text primary key,
  provider     text not null,
  type         text not null,
  payload      jsonb not null,
  received_at  timestamptz not null default now(),
  processed_at timestamptz,
  error        text
);

create index provider_events_unprocessed_idx
  on public.provider_events (received_at) where processed_at is null;
