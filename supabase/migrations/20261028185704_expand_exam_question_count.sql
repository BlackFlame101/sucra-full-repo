-- Allow a student-selected exam length while keeping every type represented.
alter table public.exams
  drop constraint if exists exams_exercise_ids_check;
alter table public.exams
  add constraint exams_exercise_ids_check
  check (
    jsonb_typeof(exercise_ids) = 'array'
    and jsonb_array_length(exercise_ids) between 3 and 12
  );

alter table public.exams
  drop constraint if exists exams_score_check;
alter table public.exams
  add constraint exams_score_check
  check (score between 0 and 120);
