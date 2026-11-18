-- Use a disposable local Socra database with all prior migrations.
begin;
do $$
declare
  owner uuid := gen_random_uuid(); outsider uuid := gen_random_uuid();
  course uuid; other_course uuid; inquiry uuid;
  upload_a uuid := gen_random_uuid(); upload_b uuid := gen_random_uuid();
  foreign_upload uuid := gen_random_uuid();
  digest text := repeat('b',64);
  result jsonb; path text; j public.processing_jobs;
  vector text := '[' || trim(trailing ',' from repeat('0.1,',768)) || ']';
  chunks jsonb; candidate uuid; n integer;
  extra_uploads uuid[] := '{}';
begin
  insert into auth.users(id) values (owner),(outsider);
  insert into public.courses(user_id,name) values (owner,'Fixture') returning id into course;
  insert into public.courses(user_id,name) values (outsider,'Foreign fixture') returning id into other_course;
  insert into public.sessions(course_id,title) values (course,'Fixture') returning id into inquiry;
  if has_function_privilege('authenticated','public.finish_pdf_upload(uuid,uuid,text)','execute') then
    raise exception 'browser can call privileged upload function';
  end if;
  if public.reserve_pdf_upload(outsider,course,upload_a,'Fixture.pdf',200,digest)->>'state' <> 'missing' then
    raise exception 'non-owner reserved an upload';
  end if;
  if public.reserve_pdf_upload(owner,course,upload_a,'Fixture.pdf',52428801,digest)->>'state' <> 'invalid' then
    raise exception 'oversized file was authorized';
  end if;
  result := public.reserve_pdf_upload(owner,course,upload_a,'Fixture.pdf',200,digest);
  path := result->>'path';
  if public.finish_pdf_upload(owner,upload_a)->>'state' <> 'incomplete' then
    raise exception 'upload finalized without a stored object';
  end if;
  -- Storage API writes equivalent metadata on completion. This fixture does not upload bytes.
  insert into storage.objects(bucket_id,name,metadata) values
    ('documents',path,jsonb_build_object('size',199,'mimetype','application/pdf'));
  if public.finish_pdf_upload(owner,upload_a)->>'state' <> 'incomplete' then
    raise exception 'truncated object accepted';
  end if;
  update storage.objects set metadata=jsonb_build_object('size',200,'mimetype','application/pdf') where name=path;
  if public.finish_pdf_upload(outsider,upload_a)->>'state' <> 'missing'
     or public.finish_pdf_upload(owner,upload_a)->>'state' <> 'finished'
     or public.finish_pdf_upload(owner,upload_a)->>'state' <> 'finished' then
    raise exception 'invalid ownership or completion replay';
  end if;
  if (select count(*) from public.processing_jobs where document_id=upload_a) <> 1 then
    raise exception 'duplicate indexing job';
  end if;
  select * into j from public.claim_processing_job('index') where document_id=upload_a;
  perform public.publish_pdf_pages(j.id,j.lease_token,digest,'["Spark window functions"]');
  chunks := jsonb_build_array(jsonb_build_object('content','Spark window functions',
      'embedding',vector,'page_number',1,'chunk_index',0));
  if not public.activate_versioned_pdf_index(j.id,j.lease_token,digest,1,chunks,'fixture') then
    raise exception 'could not publish source vectors';
  end if;

  for i in 1..2 loop
    candidate := case when i=1 then upload_b else foreign_upload end;
    path := (public.reserve_pdf_upload(case when i=1 then owner else outsider end,
      case when i=1 then course else other_course end,candidate,'Copy.pdf',200,digest))->>'path';
    insert into storage.objects(bucket_id,name,metadata) values
      ('documents',path,jsonb_build_object('size',200,'mimetype','application/pdf'));
    perform public.finish_pdf_upload(case when i=1 then owner else outsider end,candidate);
    select * into j from public.claim_processing_job('index') where document_id=candidate;
    perform public.publish_pdf_pages(j.id,j.lease_token,digest,'["Spark window functions"]');
    if public.reuse_pdf_index(j.id,j.lease_token,digest,1,'different-config') then
      raise exception 'vectors reused across incompatible configurations';
    end if;
    if public.reuse_pdf_index(j.id,j.lease_token,digest,1,'fixture') is distinct from (i=1) then
      raise exception 'same-owner dedup or cross-owner isolation failed';
    end if;
  end loop;

  for i in 1..8 loop
    candidate := gen_random_uuid();
    extra_uploads := array_append(extra_uploads,candidate);
    result := public.reserve_pdf_upload(owner,course,candidate,'Queue.pdf',200,digest);
    if result->>'state' <> 'pending' then raise exception 'premature upload quota'; end if;
    insert into storage.objects(bucket_id,name,metadata) values
      ('documents',result->>'path',jsonb_build_object('size',200,'mimetype','application/pdf'));
  end loop;
  if public.reserve_pdf_upload(owner,course,gen_random_uuid(),'Extra.pdf',200,digest)->>'state' <> 'upload_quota' then
    raise exception 'pending upload limit not enforced';
  end if;
  foreach candidate in array extra_uploads loop
    result := public.finish_pdf_upload(owner,candidate);
    exit when result->>'state' = 'processing_quota';
    if result->>'state' <> 'finished' then raise exception 'unexpected finish state'; end if;
  end loop;
  if result->>'state' <> 'processing_quota' or exists(select from public.documents where id=candidate) then
    raise exception 'processing limit failed or a rejected upload created a document';
  end if;
  if not public.cancel_pdf_upload(owner,candidate)
     or public.finish_pdf_upload(owner,candidate)->>'state' <> 'expired' then
    raise exception 'cancelled upload reached processing';
  end if;

  select count(*) into n from public.match_course_terms(course,'Spark OR window',10);
  if n <> 2 or exists(select from public.match_course_terms(other_course,'Spark',10)) then
    raise exception 'keyword retrieval did not respect scope and readiness';
  end if;
  insert into public.messages(session_id,role,content,chat_request_id) values (inquiry,'user','old prompt',upload_a);
  insert into public.messages(session_id,role,content,created_at)
    select inquiry,'assistant','newer answer',clock_timestamp() + i * interval '1 second' from generate_series(1,40) i;
  result := public.load_study_turn(inquiry,owner,upload_a);
  if jsonb_array_length(result->'recent') <> 32
     or jsonb_array_length(result->'request_messages') <> 1
     or public.load_study_turn(inquiry,outsider,upload_a) is not null then
    raise exception 'bounded snapshot lost an old retry or exposed another user';
  end if;
end;
$$;
rollback;
