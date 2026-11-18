-- Run against a disposable local Socra database.
begin;
do $$
declare
  owner_id uuid := gen_random_uuid(); outsider uuid := gen_random_uuid();
  course_id uuid; inquiry uuid; exam_id uuid; e public.exams; j public.exam_jobs;
  plan jsonb := '{"topic":"Databases","question_count":3,"exercise_types":["short_answer"],"difficulty":"beginner","provider":"google","language":"en"}';
  slots jsonb := '[{"type":"short_answer"},{"type":"short_answer"},{"type":"short_answer"}]';
  question jsonb := '{"concept":"Databases","difficulty":"beginner","bloom_level":"understand","prompt":"Explain the database concept.","citations":[],"hints":[],"expected_answer":"Private","rubric":[],"common_mistakes":[],"exercise_type":"short_answer","exercise_data":{}}';
  grade jsonb; stale uuid; ids jsonb; q text;
begin
  insert into auth.users(id) values(owner_id),(outsider);
  insert into public.courses(user_id,name) values(owner_id,'Exam fixture') returning id into course_id;
  insert into public.sessions(course_id,title) values(course_id,'Exam fixture') returning id into inquiry;
  if has_function_privilege('authenticated','public.claim_exam_job(text)','execute') then raise exception 'public job access'; end if;
  if public.queue_exam(inquiry,course_id,outsider,plan) is not null then raise exception 'cross-user start'; end if;
  exam_id := public.queue_exam(inquiry,course_id,owner_id,plan);
  if public.queue_exam(inquiry,course_id,owner_id,plan) is distinct from exam_id then raise exception 'duplicate exam'; end if;
  select * into j from public.claim_exam_job('generation');
  perform public.save_exam_plan(j.id,j.lease_token,slots);
  if public.save_exam_slot(j.id,j.lease_token,2,question) <> 'saved'
     or public.save_exam_slot(j.id,j.lease_token,0,question) <> 'duplicate'
     or public.publish_exam(j.id,j.lease_token) then raise exception 'partial exam published or duplicate accepted'; end if;
  stale := j.lease_token;
  update public.exam_jobs set lease_until=now()-interval '1 second' where id=j.id;
  select * into j from public.claim_exam_job('generation');
  if j.attempts<>2 or public.save_exam_slot(j.id,stale,0,question)<>'stale' then raise exception 'old lease still active'; end if;
  for slot in 0..1 loop
    if public.save_exam_slot(j.id,j.lease_token,slot,question || jsonb_build_object('prompt','Distinct prompt '||slot)) <> 'saved' then
      raise exception 'slot could not be persisted';
    end if;
  end loop;
  if not public.publish_exam(j.id,j.lease_token) then raise exception 'complete exam did not publish'; end if;
  select exercise_ids into ids from public.exams where id=exam_id;
  if (select exam_slot from public.exercises where id=(ids->>0)::uuid) <> 0 then raise exception 'slot order lost'; end if;
  for q in select value from jsonb_array_elements_text(ids) loop
    if public.write_exam_answer(exam_id,owner_id,q::uuid,'answer','') <> 'saved'
       or public.write_exam_answer(exam_id,owner_id,q::uuid,'answer','') <> 'saved'
       or public.write_exam_answer(exam_id,owner_id,q::uuid,'stale answer','') <> 'conflict'
       or public.write_exam_answer(exam_id,outsider,q::uuid,'other','') <> 'missing' then
      raise exception 'answer replay, conflict or ownership failed';
    end if;
  end loop;
  select * into e from public.exams where id=exam_id;
  if public.queue_exam_grading(exam_id,owner_id,'{}','{"provider":"google"}')<>'conflict'
     or public.queue_exam_grading(exam_id,owner_id,e.answers,'{"provider":"google"}')<>'grading'
     or public.queue_exam_grading(exam_id,owner_id,e.answers,'{"provider":"google"}')<>'grading'
     or public.write_exam_answer(exam_id,owner_id,(ids->>0)::uuid,'changed','answer')<>'closed' then
    raise exception 'submission was not idempotent or did not freeze answers';
  end if;
  select * into j from public.claim_exam_job('grading');
  for q in select value from jsonb_array_elements_text(ids) loop
    grade := jsonb_build_object('exercise_id',q,'answer','answer','score',8,'max_score',10,'feedback','Feedback',
      'error_category','partial','criterion_feedback','[]'::jsonb,'citations','[]'::jsonb,'next_step','Review');
    if not public.save_exam_grade(j.id,j.lease_token,grade) or not public.save_exam_grade(j.id,j.lease_token,grade) then
      raise exception 'grade replay failed';
    end if;
  end loop;
  if not public.publish_exam_grades(j.id,j.lease_token,null) then raise exception 'grades did not publish'; end if;
  select * into e from public.exams where id=exam_id;
  if e.score<>24 or e.status<>'completed' or jsonb_array_length(e.results)<>3
     or (select count(*) from public.exercise_attempts where session_id=inquiry)<>3 then raise exception 'duplicate or missing grades'; end if;
end;
$$;
rollback;
