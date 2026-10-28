-- Private storage for mixed exam sessions and saved student answers.
create table if not exists public.exams (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  topic text not null default '',
  exercise_ids jsonb not null check (
    jsonb_typeof(exercise_ids) = 'array' and jsonb_array_length(exercise_ids) = 3
  ),
  answers jsonb not null default '{}'::jsonb check (jsonb_typeof(answers) = 'object'),
  status text not null default 'in_progress' check (status in ('in_progress', 'completed')),
  score integer check (score between 0 and 30),
  results jsonb not null default '[]'::jsonb check (jsonb_typeof(results) = 'array'),
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists exams_user_session_created_idx
  on public.exams (user_id, session_id, created_at desc);

alter table public.exams enable row level security;
comment on table public.exams is
  'Private exam sessions. Correct answers stay in the linked private exercises table; only the backend service role may access exam records.';
revoke all on table public.exams from anon, authenticated;
grant all on table public.exams to service_role;
drop policy if exists exams_browser_denied on public.exams;
create policy exams_browser_denied
  on public.exams
  for all
  to anon, authenticated
  using (false)
  with check (false);
