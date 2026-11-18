-- Run with psql -v ON_ERROR_STOP=1 against a local disposable schema only.
begin;

do $$
declare
  owner_id uuid := gen_random_uuid();
  outsider uuid := gen_random_uuid();
  course_id uuid;
  session_id uuid;
  doc_id uuid := gen_random_uuid();
  doc public.documents;
  j public.processing_jobs;
  summary_job public.processing_jobs;
  d jsonb;
  digest text := repeat('a', 64);
  vec text := '[' || trim(trailing ',' from repeat('0.1,', 768)) || ']';
  rows jsonb;
  old_lease uuid;
begin
  insert into auth.users(id) values (owner_id), (outsider);
  insert into public.courses(user_id, name) values (owner_id, 'Local fixture') returning id into course_id;
  insert into public.sessions(course_id, title) values (course_id, 'Local fixture') returning id into session_id;
  if public.acquire_chat_turn(session_id, outsider, gen_random_uuid()) then
    raise exception 'unauthorized chat lease';
  end if;
  old_lease := gen_random_uuid();
  if not public.acquire_chat_turn(session_id, owner_id, old_lease)
     or public.acquire_chat_turn(session_id, owner_id, gen_random_uuid()) then
    raise exception 'chat lease did not serialize overlapping turns';
  end if;
  perform public.release_chat_turn(session_id, old_lease);

  if has_function_privilege('authenticated', 'public.claim_processing_job(text)', 'EXECUTE') then
    raise exception 'queue is accessible to a browser role';
  end if;
  d := public.queue_pdf_upload(owner_id, course_id, doc_id, 'Fixture.pdf',
    owner_id::text || '/' || course_id::text || '/' || doc_id::text || '.pdf', 100, digest);
  perform public.queue_pdf_upload(owner_id, course_id, doc_id, 'Fixture.pdf',
    owner_id::text || '/' || course_id::text || '/' || doc_id::text || '.pdf', 100, digest);
  if d->>'index_status' <> 'pending' or (select count(*) from public.processing_jobs where document_id = doc_id) <> 1 then
    raise exception 'duplicate upload or incorrect initial status';
  end if;
  if public.queue_pdf_retry(outsider, doc_id, 'index') is not null then
    raise exception 'non-owner queued a retry';
  end if;
  select * into j from public.claim_processing_job('index') where document_id = doc_id;
  if not public.publish_pdf_pages(j.id, j.lease_token, digest, '["Text"]'::jsonb) then
    raise exception 'extraction did not publish';
  end if;
  select * into summary_job from public.claim_processing_job('summary') where document_id = doc_id;
  if summary_job.pages <> '["Text"]'::jsonb then raise exception 'summary did not reuse pages'; end if;

  rows := jsonb_build_array(jsonb_build_object('content', 'Text', 'embedding', vec, 'page_number', 1, 'chunk_index', 0));
  if not public.activate_document_index(j.id, j.lease_token, digest, 1, rows) then
    raise exception 'index was not activated';
  end if;
  select * into doc from public.documents where id = doc_id;
  if doc.index_status <> 'ready' or doc.summary_status <> 'pending' or
     (select count(*) from public.match_embeddings(vec::extensions.vector, 5, course_id)) <> 1 then
    raise exception 'index readiness waited for summary';
  end if;
  perform public.fail_pdf_job(summary_job.id, summary_job.lease_token, 'Fixture failure', true);
  select * into doc from public.documents where id = doc_id;
  if doc.index_status <> 'ready' or doc.summary_status <> 'failed' then
    raise exception 'summary failure changed index readiness';
  end if;

  perform public.queue_pdf_retry(owner_id, doc_id, 'index');
  select * into j from public.claim_processing_job('index') where document_id = doc_id;
  old_lease := j.lease_token;
  update public.processing_jobs set lease_until = now() - interval '1 second' where id = j.id;
  select * into j from public.claim_processing_job('index') where document_id = doc_id;
  if j.attempts <> 2 or public.publish_pdf_pages(j.id, old_lease, digest, '["Stale"]'::jsonb) then
    raise exception 'worker restart did not invalidate the old lease';
  end if;
  perform public.publish_pdf_pages(j.id, j.lease_token, digest, '["Text"]'::jsonb);
  begin
    perform public.activate_document_index(j.id, j.lease_token, digest, 1,
      jsonb_build_array(jsonb_build_object('content', 'Invalid', 'embedding', '[0]', 'page_number', 1, 'chunk_index', 0)));
    raise exception 'bad vector was accepted';
  exception when data_exception then
    null;
  end;
  if (select count(*) from public.match_embeddings(vec::extensions.vector, 5, course_id)) <> 1 then
    raise exception 'failed replacement removed the old index';
  end if;
  delete from public.documents where id = doc_id;
  if public.activate_document_index(j.id, j.lease_token, digest, 1, rows)
     or exists (select from public.processing_jobs where document_id = doc_id) then
    raise exception 'deleted document was activated';
  end if;
end;
$$;

rollback;
