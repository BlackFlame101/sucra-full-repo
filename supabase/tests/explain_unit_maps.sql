-- Run only on a disposable Socra database with the Unit Map migration applied.
begin;
do $$
declare
  owner uuid := gen_random_uuid();
  outsider uuid := gen_random_uuid();
  course uuid;
  source uuid := gen_random_uuid();
  copy uuid := gen_random_uuid();
  upload uuid := gen_random_uuid();
  digest text := repeat('a', 64);
  version text := 'fixture-v1';
  skeleton jsonb := '{"extractor_version":"fixture-v1","units":[],"text_hash":"valid"}';
  j public.processing_jobs;
  claimed public.processing_jobs;
  chunks jsonb := jsonb_build_array(jsonb_build_object('content','synthetic source',
    'embedding','[' || trim(trailing ',' from repeat('0.1,',768)) || ']', 'page_number',1,'chunk_index',0));
  result jsonb;
  role_name text;
  entry regprocedure;
begin
  insert into auth.users(id) values (owner),(outsider);
  insert into public.courses(user_id,name) values (owner,'Unit Map fixture') returning id into course;
  result := public.reserve_pdf_upload(owner,course,source,'Source.pdf',100,digest);
  insert into storage.objects(bucket_id,name,metadata)
    values ('documents',result->>'path','{"size":100,"mimetype":"application/pdf"}');
  if public.finish_pdf_upload(owner,source)->>'state' is distinct from 'finished'
    then raise exception 'source upload failed'; end if;
  select * into j from public.claim_processing_job('index');
  if j.document_id is distinct from source or
     not public.publish_pdf_pages(j.id,j.lease_token,digest,'["synthetic source"]') or
     not public.activate_pdf_index_with_unit_map(j.id,j.lease_token,digest,1,chunks,'fixture',version)
    then raise exception 'initial activation failed'; end if;
  select * into j from public.processing_jobs where document_id=source and kind='unit_map';
  if j.status is distinct from 'queued' or
     public.queue_explain_unit_map(source,1,owner,version) or
     public.queue_explain_unit_map(source,1,outsider,version)
    then raise exception 'initial enqueue, duplicate or owner check failed'; end if;
  select * into claimed from public.claim_processing_job('unit_map');
  if claimed.id is distinct from j.id or
     public.publish_explain_unit_map(j.id,gen_random_uuid(),skeleton,version)
    then raise exception 'claim or wrong lease check failed'; end if;
  update public.processing_jobs set lease_until=now()-interval '1 second' where id=j.id;
  if public.publish_explain_unit_map(j.id,claimed.lease_token,skeleton,version)
    then raise exception 'expired lease accepted'; end if;
  select * into claimed from public.claim_processing_job('unit_map');
  begin
    perform public.publish_explain_unit_map(j.id,claimed.lease_token,skeleton-'text_hash',version);
    raise exception 'missing hash accepted';
  exception when invalid_parameter_value then null;
  end;
  begin
    perform public.publish_explain_unit_map(j.id,claimed.lease_token,skeleton||'{"text_hash":" "}',version);
    raise exception 'blank hash accepted';
  exception when invalid_parameter_value then null;
  end;
  if not public.publish_explain_unit_map(j.id,claimed.lease_token,skeleton,version)
     or not public.queue_explain_unit_map(source,1,owner,version)
    then raise exception 'publish or already-current map check failed'; end if;

  result := public.reserve_pdf_upload(owner,course,copy,'Copy.pdf',100,digest);
  insert into storage.objects(bucket_id,name,metadata)
    values ('documents',result->>'path','{"size":100,"mimetype":"application/pdf"}');
  if public.finish_pdf_upload(owner,copy)->>'state' is distinct from 'finished'
    then raise exception 'copy upload failed'; end if;
  select * into j from public.claim_processing_job('index');
  if j.document_id is distinct from copy or
     not public.publish_pdf_pages(j.id,j.lease_token,digest,'["synthetic source"]') or
     not public.reuse_pdf_index_with_unit_map(j.id,j.lease_token,digest,1,'fixture',version)
    then raise exception 'index reuse failed'; end if;
  select * into claimed from public.claim_processing_job('unit_map');
  if claimed.document_id is distinct from copy or
     not public.fail_explain_unit_map(claimed.id,claimed.lease_token,true) or
     public.queue_explain_unit_map(copy,1,owner,version) or
     not public.retry_failed_explain_unit_map(copy)
    then raise exception 'failed-job recovery failed'; end if;
  select * into claimed from public.claim_processing_job('unit_map');
  update public.documents set index_generation=2 where id=copy;
  if public.publish_explain_unit_map(claimed.id,claimed.lease_token,skeleton,version)
    then raise exception 'stale generation accepted'; end if;

  update public.documents set content_hash=repeat('b',64), index_config='fixture:ocr-tesseract-v1:eng' where id=source;
  if not public.queue_explain_unit_map(source,1,owner,version,'["new OCR pages"]') then
    raise exception 'completed job did not requeue after source changed';
  end if;
  select * into j from public.processing_jobs where document_id=source and kind='unit_map';
  if j.content_hash is distinct from repeat('b',64) or j.pages is distinct from '["new OCR pages"]'::jsonb
     or not j.use_ocr or j.lease_token is not null or j.lease_until is not null
    then raise exception 'completed job retained stale fields'; end if;
  select * into j from public.claim_processing_job('unit_map');
  update public.explain_unit_maps set generation=2 where document_id=source;
  if public.publish_explain_unit_map(j.id,j.lease_token,skeleton,version)
    then raise exception 'newer stored map allowed publication'; end if;
  if not exists (select from public.processing_jobs where id=j.id and status='failed' and lease_token is null)
    then raise exception 'newer stored map did not terminally reject publication'; end if;

  with documents as (
    insert into public.documents(course_id,filename,storage_path,index_status,summary_status)
      select course,'Backlog.pdf','synthetic/'||gen_random_uuid(),'ready','ready' from generate_series(1,12)
      returning id,index_generation
  )
  insert into public.processing_jobs(document_id,generation,kind,status)
    select id,index_generation,'unit_map','queued' from documents;
  if not public.pdf_processing_available(owner) then raise exception 'Unit Map backlog consumed PDF quota'; end if;
  result := public.reserve_pdf_upload(owner,course,upload,'New.pdf',100,digest);
  insert into storage.objects(bucket_id,name,metadata)
    values ('documents',result->>'path','{"size":100,"mimetype":"application/pdf"}');
  if public.finish_pdf_upload(owner,upload)->>'state' is distinct from 'finished'
    then raise exception 'Unit Map backlog blocked upload'; end if;
  update public.processing_jobs set kind='index' where status='queued' and kind='unit_map'
    and document_id in (select id from public.documents where filename='Backlog.pdf');
  if public.pdf_processing_available(owner) then raise exception 'index backlog escaped the quota'; end if;

  foreach role_name in array array['anon','authenticated'] loop
    if has_table_privilege(role_name,'public.explain_unit_maps','SELECT,INSERT,UPDATE,DELETE') then
      raise exception 'browser role has map privileges';
    end if;
    for entry in select p.oid::regprocedure from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname like '%unit_map%'
    loop
      if has_function_privilege(role_name,entry,'EXECUTE') or not has_function_privilege('service_role',entry,'EXECUTE')
        then raise exception 'incorrect execute grants for %',entry; end if;
    end loop;
  end loop;
end;
$$;

create function pg_temp.reject_unit_map_insert() returns trigger language plpgsql as $$
begin
  raise exception 'synthetic Unit Map enqueue failure';
end;
$$;
create trigger reject_unit_map_insert before insert on public.processing_jobs
  for each row when (new.kind = 'unit_map') execute function pg_temp.reject_unit_map_insert();

do $$
declare
  owner uuid := gen_random_uuid();
  course uuid;
  doc uuid;
  digest text := repeat('c',64);
  j public.processing_jobs;
  chunks jsonb := jsonb_build_array(jsonb_build_object('content','isolated source',
    'embedding','[' || trim(trailing ',' from repeat('0.1,',768)) || ']', 'page_number',1,'chunk_index',0));
begin
  insert into auth.users(id) values (owner);
  insert into public.courses(user_id,name) values (owner,'Enqueue failure fixture') returning id into course;
  for i in 1..2 loop
    insert into public.documents(course_id,filename,storage_path,index_status,index_generation)
      values (course,'Isolation.pdf','synthetic/'||gen_random_uuid(),'pending',1) returning id into doc;
    insert into public.processing_jobs(document_id,generation,kind,content_hash,status,lease_token,lease_until)
      values (doc,1,'index',digest,'running',gen_random_uuid(),now()+interval '1 minute') returning * into j;
    if i=1 then
      if not public.activate_pdf_index_with_unit_map(j.id,j.lease_token,digest,1,chunks,'isolation','fixture-v1')
        then raise exception 'enqueue error prevented index activation'; end if;
    else
      if not public.reuse_pdf_index_with_unit_map(j.id,j.lease_token,digest,1,'isolation','fixture-v1')
        then raise exception 'enqueue error prevented index reuse'; end if;
    end if;
    if not exists(select from public.documents where id=doc and index_status='ready')
       or not exists(select from public.processing_jobs where id=j.id and status='ready')
       or exists(select from public.processing_jobs where document_id=doc and kind='unit_map')
      then raise exception 'incorrect state after enqueue error'; end if;
  end loop;
end;
$$;
select 'Unit Map lifecycle, quota, grants and enqueue failure isolation passed' as result;
rollback;
