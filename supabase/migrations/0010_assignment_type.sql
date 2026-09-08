-- 0010: add 'assignment' to the lesson type enum.
--
-- Alone in its own migration on purpose. Postgres will not let a newly added
-- enum value be *used* in the same transaction that adds it, so the tables and
-- constraints that reference it live in 0011.

alter type public.lesson_type add value if not exists 'assignment';
