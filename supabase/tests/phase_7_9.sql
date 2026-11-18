-- Run in a disposable Supabase database after applying the migration chain.
begin;
do $$
declare
  student uuid := gen_random_uuid(); other_student uuid := gen_random_uuid();
  course uuid; doc uuid := gen_random_uuid();
  j public.processing_jobs;
  digest text := repeat('a',64);
begin
  insert into auth.users(id) values(student),(other_student);
  insert into public.courses(user_id,name) values(student,'OCR fixture') returning id into course;
  perform public.queue_pdf_upload(student,course,doc,'Scan.pdf',student::text||'/'||course::text||'/'||doc::text||'.pdf',2048,digest);
  select * into j from public.claim_processing_job('index') where document_id=doc;
  if j.id is null then raise exception 'fixture index job was not claimed'; end if;
  perform public.fail_pdf_job(j.id,j.lease_token,'Scanned PDF.',true);
  if public.queue_pdf_retry(other_student,doc,'ocr') is not null then raise exception 'foreign OCR accepted'; end if;
  if public.queue_pdf_retry(student,doc,'ocr') is null then raise exception 'OCR retry failed'; end if;
  select * into j from public.claim_processing_job('index') where document_id=doc;
  if j.use_ocr is distinct from true then raise exception 'OCR retry lost mode'; end if;
  if not public.publish_pdf_pages(j.id,j.lease_token,digest,'["", "Read page two"]'::jsonb)
     or not exists(select from public.processing_jobs where document_id=doc and kind='summary' and use_ocr) then
    raise exception 'OCR page numbers or mode were lost';
  end if;
  for i in 1..4 loop
    if not public.consume_study_quota(student,'pdf_ocr') then raise exception 'quota rejected early'; end if;
  end loop;
  if public.consume_study_quota(student,'pdf_ocr') or not public.consume_study_quota(student,'pdf_retry')
    or not public.consume_study_quota(other_student,'pdf_ocr') then raise exception 'quota isolation failed'; end if;
  if has_function_privilege('authenticated','public.consume_study_quota(uuid,text)','execute')
    or has_function_privilege('authenticated','public.match_embeddings(extensions.vector,integer,uuid)','execute')
    or has_table_privilege('authenticated','public.student_profiles','update')
    or has_table_privilege('authenticated','public.library_items','insert')
    or has_column_privilege('authenticated','public.notebook_notes','source_data','update') then
    raise exception 'server-only operations are exposed';
  end if;
  delete from public.courses where id=course;
  if not exists(select from public.deleted_pdf_objects where storage_path like '%'||doc::text||'.pdf') then
    raise exception 'course cascade lost Storage cleanup';
  end if;
end;
$$;
rollback;
