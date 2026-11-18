-- Run after the Notebook migration in a disposable database.
begin;
do $$
declare
  student uuid := gen_random_uuid();
  outsider uuid := gen_random_uuid();
  course uuid;
  inquiry uuid;
  message uuid;
  existing uuid;
  created uuid;
  request uuid := gen_random_uuid();
  result jsonb;
  sample jsonb := '[{"type":"paragraph","content":[{"type":"text","text":"Captured response"}]}]';
  fingerprint text := repeat('a',64);
begin
  insert into auth.users(id) values(student),(outsider);
  insert into public.courses(user_id,name) values(student,'Notebook fixture') returning id into course;
  insert into public.sessions(course_id,title) values(course,'Fixture inquiry') returning id into inquiry;
  insert into public.messages(session_id,role,content) values(inquiry,'assistant','Captured response') returning id into message;
  insert into public.notebook_notes(user_id,course_id,title,content)
    values(student,course,'Legacy note',E'Existing text\nKeep this line') returning id into existing;
  if has_column_privilege('authenticated','public.notebook_notes','content','update') or
    has_function_privilege('authenticated','public.capture_notebook_response(uuid,uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text,jsonb,text,jsonb)','execute') then
    raise exception 'Browser can bypass Notebook ownership or optimistic concurrency';
  end if;
  result := public.capture_notebook_response(outsider,request,existing,course,inquiry,message,'tutor','[]',fingerprint,'Capture',sample,'Captured response',null);
  if result->>'state' <> 'missing' then raise exception 'A foreign response may be captured'; end if;
  result := public.capture_notebook_response(student,request,existing,course,inquiry,message,'tutor','[]',fingerprint,'Capture',sample,'Captured response',null);
  if (result->>'id')::uuid <> existing then raise exception 'Could not append to legacy note'; end if;
  perform public.capture_notebook_response(student,request,existing,course,inquiry,message,'tutor','[]',fingerprint,'Capture',sample,'Captured response',null);
  perform public.capture_notebook_response(student,gen_random_uuid(),existing,course,inquiry,message,'tutor','[]',fingerprint,'Capture',sample,'Captured response',null);
  if not exists(select from public.notebook_notes where id=existing and version=2 and
      content=E'Existing text\nKeep this line\n\nCaptured response' and jsonb_array_length(content_json->'content')=4) then
    raise exception 'Legacy content was lost or capture duplicated';
  end if;
  result := public.capture_notebook_response(student,gen_random_uuid(),null,course,inquiry,message,'tutor','[]',fingerprint,'Capture',sample,'Captured response',null);
  created := (result->>'id')::uuid;
  result := public.capture_notebook_response(student,gen_random_uuid(),null,course,inquiry,message,'tutor','[]',fingerprint,'Capture',sample,'Captured response',null);
  if created=existing or created is null or (result->>'id')::uuid <> created then raise exception 'Create deduplication failed'; end if;
  delete from public.courses where id=course;
  if not exists(select from public.notebook_notes where id=existing and course_id is null) then
    raise exception 'Deleting a course destroyed student notes';
  end if;
  if exists(select from public.notebook_sources where note_id=existing and (course_id is not null or message_id is not null)) then
    raise exception 'Deleted sources did not detach';
  end if;
end;
$$;
rollback;
