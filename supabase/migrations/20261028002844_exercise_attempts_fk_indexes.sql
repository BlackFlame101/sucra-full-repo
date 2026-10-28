create index if not exists exercise_attempts_session_idx
  on public.exercise_attempts (session_id);
create index if not exists exercise_attempts_course_idx
  on public.exercise_attempts (course_id);
