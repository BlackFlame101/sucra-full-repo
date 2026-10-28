-- Enable safely reviewed Python and read-only SQLite exercise types.
alter table public.exercises
  drop constraint if exists exercises_exercise_type_check;

alter table public.exercises
  add constraint exercises_exercise_type_check
  check (exercise_type in ('short_answer', 'multiple_choice', 'numerical', 'code', 'sql'));

comment on column public.exercises.exercise_data is
  'Private verifier data for objective, Python code, and read-only SQL exercises. Never expose reference answers before submission or explicit reveal.';

alter table public.exams
  add column if not exists requested_types jsonb not null
  default '["short_answer", "multiple_choice", "numerical"]'::jsonb;

alter table public.exams
  drop constraint if exists exams_requested_types_check;
alter table public.exams
  add constraint exams_requested_types_check
  check (
    jsonb_typeof(requested_types) = 'array'
    and jsonb_array_length(requested_types) between 1 and 5
  );
