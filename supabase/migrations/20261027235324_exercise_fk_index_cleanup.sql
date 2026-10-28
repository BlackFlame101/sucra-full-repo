-- The session_id column already has its own foreign key. Keep one constraint,
-- and index course_id independently so deletes and joins can use it directly.
alter table public.exercises
  drop constraint if exists exercises_session_owner_fkey;

create index if not exists exercises_course_id_idx
  on public.exercises (course_id);
