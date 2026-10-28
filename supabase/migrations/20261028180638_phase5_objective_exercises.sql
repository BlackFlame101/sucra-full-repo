-- Add private, validated payloads for multiple-choice and numerical exercises.
alter table public.exercises
  add column if not exists exercise_type text not null default 'short_answer',
  add column if not exists exercise_data jsonb not null default '{}'::jsonb;

alter table public.exercises
  drop constraint if exists exercises_exercise_type_check;
alter table public.exercises
  add constraint exercises_exercise_type_check
  check (exercise_type in ('short_answer', 'multiple_choice', 'numerical'));

alter table public.exercises
  drop constraint if exists exercises_exercise_data_object_check;
alter table public.exercises
  add constraint exercises_exercise_data_object_check
  check (jsonb_typeof(exercise_data) = 'object');

comment on column public.exercises.exercise_data is
  'Private verifier data: MCQ answer key/options or numerical calculation/tolerance. Never expose before attempt.';
