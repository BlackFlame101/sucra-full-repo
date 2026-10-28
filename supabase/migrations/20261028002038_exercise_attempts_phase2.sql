create table if not exists public.exercise_attempts (
  id uuid primary key default gen_random_uuid(),
  exercise_id uuid not null references public.exercises(id) on delete cascade,
  session_id uuid not null references public.sessions(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  answer text not null check (char_length(answer) between 1 and 10000),
  hints_used integer not null default 0 check (hints_used between 0 and 3),
  total_score integer not null check (total_score between 0 and 10),
  max_score integer not null default 10 check (max_score between 1 and 10),
  criterion_feedback jsonb not null check (jsonb_typeof(criterion_feedback) = 'array'),
  feedback text not null,
  error_category text not null check (error_category in ('correct', 'partial', 'conceptual', 'incomplete', 'off_topic')),
  citations jsonb not null default '[]'::jsonb check (jsonb_typeof(citations) = 'array'),
  next_step text not null,
  solution_revealed boolean not null default false,
  created_at timestamptz not null default now(),
  constraint exercise_attempts_score_bounds check (total_score <= max_score)
);

create index if not exists exercise_attempts_exercise_created_idx
  on public.exercise_attempts (exercise_id, created_at desc);
create index if not exists exercise_attempts_user_session_idx
  on public.exercise_attempts (user_id, session_id, created_at desc);

alter table public.exercise_attempts enable row level security;
comment on table public.exercise_attempts is 'Server-owned exercise attempts and grading feedback. Client access is denied; only the authenticated backend service role can read or write.';
revoke all on table public.exercise_attempts from anon, authenticated;
grant all on table public.exercise_attempts to service_role;
drop policy if exists exercise_attempts_browser_denied on public.exercise_attempts;
create policy exercise_attempts_browser_denied
  on public.exercise_attempts
  for all
  to anon, authenticated
  using (false)
  with check (false);
