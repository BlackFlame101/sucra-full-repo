-- Short-answer exercises are written only by the trusted backend. The answer,
-- rubric, and mistake notes must never be readable by browser roles.
create table if not exists public.exercises (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  user_id uuid not null references auth.users(id) on delete cascade,
  concept text not null check (char_length(concept) between 3 and 160),
  difficulty text not null check (difficulty in ('beginner', 'intermediate', 'advanced')),
  bloom_level text not null check (bloom_level in ('remember', 'understand', 'apply', 'analyze', 'evaluate', 'create')),
  prompt text not null check (char_length(prompt) between 20 and 2000),
  citations jsonb not null check (jsonb_typeof(citations) = 'array' and jsonb_array_length(citations) between 1 and 3),
  hints jsonb not null check (jsonb_typeof(hints) = 'array' and jsonb_array_length(hints) between 2 and 3),
  expected_answer text not null,
  rubric jsonb not null check (jsonb_typeof(rubric) = 'array' and jsonb_array_length(rubric) between 1 and 6),
  common_mistakes jsonb not null default '[]'::jsonb check (jsonb_typeof(common_mistakes) = 'array'),
  verification_status text not null check (verification_status in ('verified', 'rejected')),
  created_at timestamptz not null default now(),
  constraint exercises_session_owner_fkey
    foreign key (session_id) references public.sessions(id) on delete cascade
);

create index if not exists exercises_session_created_idx
  on public.exercises (session_id, created_at desc);
create index if not exists exercises_user_course_idx
  on public.exercises (user_id, course_id);

alter table public.exercises enable row level security;
comment on table public.exercises is 'Server-owned exercise records. expected_answer and rubric are private until a later authenticated attempt flow.';
revoke all on table public.exercises from anon, authenticated;
grant all on table public.exercises to service_role;
