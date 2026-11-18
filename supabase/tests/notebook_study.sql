do $$
declare
  student uuid := gen_random_uuid();
  other uuid := gen_random_uuid();
  personal_note uuid;
  first_thread jsonb;
begin
  insert into auth.users(id) values(student), (other);
  insert into public.notebook_notes(user_id,title,content,source_type)
    values(student,'Legacy text','Study content','manual') returning id into personal_note;
  assert public.open_notebook_thread(other,personal_note) is null;
  assert not has_function_privilege('authenticated','public.open_notebook_thread(uuid,uuid)','EXECUTE');
  assert not has_table_privilege('authenticated','public.notebook_flashcards','SELECT');
  first_thread := public.open_notebook_thread(student,personal_note);
  assert first_thread is not null;
  assert first_thread = public.open_notebook_thread(student,personal_note);
  assert (select content from public.notebook_notes where id=personal_note) = 'Study content';
  assert (select notebook_private from public.courses where id=(first_thread->>'courseId')::uuid);
  update public.notebook_notes set review_due='2026-12-20' where id=personal_note;
  assert (select review_due from public.notebook_notes where id=personal_note) = date '2026-12-20';
  insert into public.notebook_flashcards values(personal_note,1,'[{"question":"Q","answer":"A"}]');
  insert into public.exercises(session_id,course_id,user_id,concept,difficulty,bloom_level,prompt,citations,hints,
    expected_answer,rubric,verification_status,notebook_grounded)
    values ((first_thread->>'sessionId')::uuid,(first_thread->>'courseId')::uuid,student,'Concept','beginner',
      'understand','Explain the topic in the note.','[]','["Hint one","Hint two"]','Answer',
      '[{"criterion":"Accuracy","points":10}]','verified',true);
  begin
    update public.exercises set notebook_grounded=false where session_id=(first_thread->>'sessionId')::uuid;
    raise exception 'An ordinary exercise accepted missing citations';
  exception when check_violation then null;
  end;
end;
$$;
