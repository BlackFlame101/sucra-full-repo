alter table public.student_profiles
  add column if not exists exercise_performance jsonb not null default '[]'::jsonb
  check (jsonb_typeof(exercise_performance) = 'array');
