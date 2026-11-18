-- Existing exams retain their questions, results and status.
alter table public.exams add column question_count integer, add column preparation_error text,
  add column exam_language text;
alter table public.exams drop constraint if exists exams_status_check;
alter table public.exams add constraint exams_status_check
  check (status in ('preparing','preparation_failed','in_progress','grading','grading_failed','completed'));
alter table public.exams drop constraint if exists exams_exercise_ids_check;
alter table public.exams add constraint exams_exercise_ids_check check (
  jsonb_typeof(exercise_ids)='array' and case when status in ('preparing','preparation_failed')
  then jsonb_array_length(exercise_ids)=0 else jsonb_array_length(exercise_ids) between 3 and 12 end
);

create table public.exam_jobs (
  id uuid primary key default gen_random_uuid(),
  exam_id uuid not null references public.exams on delete cascade,
  kind text not null check (kind in ('generation','grading')),
  options jsonb not null default '{}',
  encrypted_key text,
  status text not null default 'queued' check (status in ('queued','running','ready','failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  lease_token uuid,
  lease_until timestamptz,
  unique (exam_id,kind)
);
alter table public.exercises add column exam_job_id uuid references public.exam_jobs on delete cascade,
  add column exam_slot integer;
create unique index exercises_exam_slot on public.exercises(exam_job_id,exam_slot) where exam_job_id is not null;
create index exam_jobs_queue on public.exam_jobs(kind,available_at,id) where status in ('queued','running');
alter table public.exam_jobs enable row level security;
revoke all on public.exam_jobs from public, anon, authenticated;
grant all on public.exam_jobs to service_role;

create function public.queue_exam(inquiry uuid, course uuid, owner uuid, plan jsonb, credential text default null)
returns uuid language plpgsql set search_path = '' as $$
declare e public.exams;
begin
  perform 1 from public.sessions s join public.courses c on c.id=s.course_id
    where s.id=inquiry and c.id=course and c.user_id=owner for update of s;
  if not found then return null; end if;
  select * into e from public.exams where session_id=inquiry and user_id=owner order by created_at desc limit 1 for update;
  if not found then
    insert into public.exams(session_id,course_id,user_id,topic,exercise_ids,requested_types,status,question_count,exam_language)
      values(inquiry,course,owner,plan->>'topic','[]',plan->'exercise_types','preparing',
             (plan->>'question_count')::integer,plan->>'language') returning * into e;
    insert into public.exam_jobs(exam_id,kind,options,encrypted_key) values(e.id,'generation',plan,credential);
  elsif e.status='preparation_failed' then
    update public.exams set status='preparing',preparation_error=null where id=e.id;
    update public.exam_jobs set status='queued',attempts=0,available_at=now(),encrypted_key=credential,
      options=options || jsonb_build_object('provider',plan->>'provider','model',plan->>'model')
      where exam_id=e.id and kind='generation';
  end if;
  return e.id;
end;
$$;

create function public.claim_exam_job(job_kind text)
returns setof public.exam_jobs language sql set search_path = '' as $$
  with next_job as (
    select id from public.exam_jobs where kind=job_kind
      and ((status='queued' and available_at<=now()) or (status='running' and lease_until<=now()))
    order by available_at,id limit 1 for update skip locked
  )
  update public.exam_jobs j set status='running',attempts=attempts+1,lease_token=gen_random_uuid(),
    lease_until=now()+interval '5 minutes'
  from next_job where j.id=next_job.id returning j.*;
$$;

-- Lock exam first, then job. Retry and submission use the same order.
create function public.lock_exam_job(job_id uuid, lease uuid, job_kind text)
returns public.exam_jobs language plpgsql set search_path = '' as $$
declare j public.exam_jobs;
begin
  select * into j from public.exam_jobs where id=job_id;
  if not found then return null; end if;
  perform 1 from public.exams where id=j.exam_id for update;
  if not found then return null; end if;
  select * into j from public.exam_jobs where id=job_id and lease_token=lease and status='running'
    and lease_until>clock_timestamp() and (job_kind is null or kind=job_kind) for update;
  return j;
end;
$$;

create function public.save_exam_plan(job_id uuid, lease uuid, slot_plan jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.exam_jobs;
begin
  j := public.lock_exam_job(job_id,lease,'generation');
  if j.id is null then return false; end if;
  update public.exam_jobs set options=options || jsonb_build_object('slots',slot_plan) where id=j.id;
  return true;
end;
$$;

create function public.save_exam_slot(job_id uuid, lease uuid, slot integer, question jsonb)
returns text language plpgsql set search_path = '' as $$
declare j public.exam_jobs; e public.exams;
begin
  j := public.lock_exam_job(job_id,lease,'generation');
  if j.id is null then return 'stale'; end if;
  select * into e from public.exams where id=j.exam_id;
  if e.status<>'preparing' or slot is null or slot not between 0 and e.question_count-1
     or question->>'exercise_type' is distinct from (j.options->'slots'->slot->>'type')
     or question->>'difficulty' is distinct from j.options->>'difficulty' then return 'invalid'; end if;
  if exists(select from public.exercises where exam_job_id=j.id and exam_slot=slot) then return 'saved'; end if;
  if exists(select from public.exercises where exam_job_id=j.id and
     lower(regexp_replace(trim(prompt),'[[:space:]]+',' ','g')) =
     lower(regexp_replace(trim(question->>'prompt'),'[[:space:]]+',' ','g'))) then return 'duplicate'; end if;
  insert into public.exercises(session_id,course_id,user_id,concept,difficulty,bloom_level,prompt,citations,hints,
      expected_answer,rubric,common_mistakes,verification_status,exercise_type,exercise_data,exam_job_id,exam_slot)
    values(e.session_id,e.course_id,e.user_id,question->>'concept',question->>'difficulty',question->>'bloom_level',
      question->>'prompt',question->'citations',question->'hints',question->>'expected_answer',question->'rubric',
      question->'common_mistakes','verified',question->>'exercise_type',
      (question->'exercise_data') || '{"for_exam":true}'::jsonb,j.id,slot);
  return 'saved';
end;
$$;

create function public.publish_exam(job_id uuid, lease uuid)
returns boolean language plpgsql set search_path = '' as $$
declare j public.exam_jobs; ids jsonb;
begin
  j := public.lock_exam_job(job_id,lease,'generation');
  if j.id is null then return false; end if;
  select jsonb_agg(id order by exam_slot) into ids from public.exercises where exam_job_id=j.id;
  update public.exams set exercise_ids=ids,status='in_progress',preparation_error=null
    where id=j.exam_id and status='preparing' and question_count=jsonb_array_length(ids);
  if not found then return false; end if;
  update public.exam_jobs set status='ready',encrypted_key=null,lease_token=null,lease_until=null where id=j.id;
  return true;
end;
$$;

create function public.write_exam_answer(exam uuid, owner uuid, question uuid, answer text, previous text default null)
returns text language plpgsql set search_path = '' as $$
declare e public.exams; saved text;
begin
  select * into e from public.exams where id=exam and user_id=owner for update;
  if not found then return 'missing'; end if;
  if e.status<>'in_progress' or not (e.exercise_ids ? question::text) then return 'closed'; end if;
  if answer is null or char_length(trim(answer)) not between 1 and 10000 then return 'invalid'; end if;
  saved := coalesce(e.answers->>question::text,'');
  if saved=answer then return 'saved'; end if;
  if previous is not null and previous<>saved then return 'conflict'; end if;
  update public.exams set answers=jsonb_set(answers,array[question::text],to_jsonb(answer)) where id=e.id;
  return 'saved';
end;
$$;

create function public.queue_exam_grading(exam uuid, owner uuid, expected_answers jsonb, model_options jsonb,
  credential text default null)
returns text language plpgsql set search_path = '' as $$
declare e public.exams;
begin
  select * into e from public.exams where id=exam and user_id=owner for update;
  if not found then return 'missing'; end if;
  if e.status in ('completed','grading') then return e.status; end if;
  if e.status not in ('in_progress','grading_failed') then return 'closed'; end if;
  if e.answers is distinct from expected_answers then return 'conflict'; end if;
  if exists(select from jsonb_array_elements_text(e.exercise_ids) as q(id)
            where nullif(trim(e.answers->>q.id),'') is null) then return 'incomplete'; end if;
  update public.exams set status='grading',preparation_error=null,
    results=case when e.status='in_progress' then coalesce(
      (select jsonb_agg(r) from jsonb_array_elements(e.results) r where r->>'answer'=e.answers->>(r->>'exercise_id')),'[]') else results end
    where id=e.id;
  insert into public.exam_jobs(exam_id,kind,options,encrypted_key)
    values(e.id,'grading',model_options,credential)
    on conflict (exam_id,kind) do update set status='queued',attempts=0,available_at=now(),
      options=excluded.options,encrypted_key=excluded.encrypted_key,lease_until=null,lease_token=null;
  return 'grading';
end;
$$;

create function public.save_exam_grade(job_id uuid, lease uuid, grade jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.exam_jobs; e public.exams; question text;
begin
  j := public.lock_exam_job(job_id,lease,'grading');
  if j.id is null then return false; end if;
  select * into e from public.exams where id=j.exam_id;
  question := grade->>'exercise_id';
  if e.status<>'grading' or not (e.exercise_ids ? question) then return false; end if;
  if exists(select from jsonb_array_elements(e.results) r where r->>'exercise_id'=question) then return true; end if;
  insert into public.exercise_attempts(exercise_id,session_id,course_id,user_id,answer,hints_used,total_score,max_score,
      criterion_feedback,feedback,error_category,citations,next_step)
    values(question::uuid,e.session_id,e.course_id,e.user_id,e.answers->>question,0,(grade->>'score')::integer,
      (grade->>'max_score')::integer,grade->'criterion_feedback',grade->>'feedback',grade->>'error_category',
      grade->'citations',grade->>'next_step');
  update public.exams set results=results || jsonb_build_array(grade) where id=e.id;
  return true;
end;
$$;

create function public.publish_exam_grades(job_id uuid, lease uuid, student_profile jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.exam_jobs; e public.exams; score_value integer; ordered jsonb;
begin
  j := public.lock_exam_job(job_id,lease,'grading');
  if j.id is null then return false; end if;
  select * into e from public.exams where id=j.exam_id;
  select sum((grades.result->>'score')::integer),jsonb_agg(grades.result order by q.position) into score_value,ordered
    from jsonb_array_elements_text(e.exercise_ids) with ordinality as q(id,position)
    join lateral (select r.result from jsonb_array_elements(e.results) as r(result)
      where r.result->>'exercise_id'=q.id limit 1) grades on true;
  if e.status<>'grading' or jsonb_array_length(ordered) is distinct from jsonb_array_length(e.exercise_ids) then
    return false;
  end if;
  update public.exams set status='completed',score=score_value,results=ordered,completed_at=now(),preparation_error=null
    where id=e.id;
  if student_profile is not null then
    insert into public.student_profiles(session_id,user_id,mastered_concepts,fragile_concepts,misconception_history,
      bloom_progression,total_exchanges,exercise_performance)
      select e.session_id,e.user_id,p.mastered_concepts,p.fragile_concepts,p.misconception_history,
        p.bloom_progression,p.total_exchanges,p.exercise_performance
      from jsonb_populate_record(null::public.student_profiles,student_profile) p
    on conflict (session_id) do update set
      mastered_concepts=excluded.mastered_concepts,fragile_concepts=excluded.fragile_concepts,
      misconception_history=excluded.misconception_history,bloom_progression=excluded.bloom_progression,
      total_exchanges=excluded.total_exchanges,exercise_performance=excluded.exercise_performance;
  end if;
  update public.exam_jobs set status='ready',encrypted_key=null,lease_token=null,lease_until=null where id=j.id;
  return true;
end;
$$;

create function public.fail_exam_job(job_id uuid, lease uuid, message text, permanent boolean)
returns boolean language plpgsql set search_path = '' as $$
declare j public.exam_jobs; terminal boolean;
begin
  j := public.lock_exam_job(job_id,lease,null);
  if j.id is null then return false; end if;
  terminal := permanent or j.attempts>=3;
  update public.exam_jobs set status=case when terminal then 'failed' else 'queued' end,
    available_at=now()+make_interval(secs=>10*power(2,least(j.attempts,3))),
    lease_token=null,lease_until=null,encrypted_key=case when terminal then null else encrypted_key end where id=j.id;
  update public.exams set preparation_error=case when terminal then message else null end,
    status=case when not terminal then status when j.kind='generation' then 'preparation_failed' else 'grading_failed' end
    where id=j.exam_id;
  return true;
end;
$$;

revoke execute on function public.queue_exam(uuid,uuid,uuid,jsonb,text), public.claim_exam_job(text),
 public.lock_exam_job(uuid,uuid,text), public.save_exam_plan(uuid,uuid,jsonb), public.save_exam_slot(uuid,uuid,integer,jsonb),
 public.publish_exam(uuid,uuid), public.write_exam_answer(uuid,uuid,uuid,text,text), public.queue_exam_grading(uuid,uuid,jsonb,jsonb,text),
 public.save_exam_grade(uuid,uuid,jsonb), public.publish_exam_grades(uuid,uuid,jsonb), public.fail_exam_job(uuid,uuid,text,boolean)
 from public, anon, authenticated;
grant execute on function public.queue_exam(uuid,uuid,uuid,jsonb,text), public.claim_exam_job(text),
 public.lock_exam_job(uuid,uuid,text), public.save_exam_plan(uuid,uuid,jsonb), public.save_exam_slot(uuid,uuid,integer,jsonb),
 public.publish_exam(uuid,uuid), public.write_exam_answer(uuid,uuid,uuid,text,text), public.queue_exam_grading(uuid,uuid,jsonb,jsonb,text),
 public.save_exam_grade(uuid,uuid,jsonb), public.publish_exam_grades(uuid,uuid,jsonb), public.fail_exam_job(uuid,uuid,text,boolean)
 to service_role;
