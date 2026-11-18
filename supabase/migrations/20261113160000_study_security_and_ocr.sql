-- The existing worker owns extraction and model calls. OCR is opt-in per index job.
alter table public.processing_jobs add column use_ocr boolean not null default false;

create or replace function public.queue_pdf_retry(owner_id uuid, document uuid, job_kind text, credential text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare d public.documents; j public.processing_jobs; parent public.processing_jobs;
begin
  select doc.* into d from public.documents doc join public.courses c on c.id = doc.course_id
    where doc.id = document and c.user_id = owner_id for update of doc;
  if not found or split_part(d.storage_path, '/', 1) <> owner_id::text or job_kind not in ('index','summary','ocr') then
    return null;
  end if;
  select * into j from public.processing_jobs
    where document_id=d.id and kind=case when job_kind='ocr' then 'index' else job_kind end
      and generation=d.index_generation;
  if found and j.status in ('queued','running') then return to_jsonb(d); end if;
  if job_kind in ('index','ocr') then
    update public.documents set index_generation=index_generation+1,
      index_stage=case when job_kind='ocr' then 'OCR queued' else 'Queued for indexing' end,
      index_status=case when index_status='ready' then 'ready' else 'pending' end, processing_error=null,
      summary_status=case when summary_stage is not null then 'pending' else summary_status end,
      summary_stage=null, summary_error=null where id=d.id returning * into d;
    delete from public.processing_jobs where document_id=d.id;
    insert into public.processing_jobs(kind,document_id,generation,content_hash,encrypted_key,use_ocr)
      values('index',d.id,d.index_generation,coalesce(d.content_hash,j.content_hash),credential,job_kind='ocr' or coalesce(j.use_ocr,false));
  elsif d.index_status='ready' then
    if d.index_stage is not null then return to_jsonb(d); end if;
    select * into parent from public.processing_jobs where document_id=d.id and kind='index' and generation=d.index_generation;
    update public.documents set summary_status='pending', summary_stage='Course Map queued', summary_error=null
      where id=d.id returning * into d;
    insert into public.processing_jobs(kind,document_id,generation,content_hash,pages,encrypted_key,use_ocr)
      values('summary',d.id,d.index_generation,d.content_hash,j.pages,credential,coalesce(parent.use_ocr,false))
      on conflict (document_id,kind,generation) do update set status='queued',available_at=now(),attempts=0,
        lease_token=null,lease_until=null,encrypted_key=excluded.encrypted_key;
  else
    return null;
  end if;
  return to_jsonb(d);
end;
$$;

create or replace function public.publish_pdf_pages(job_id uuid, lease uuid, digest text, source_pages jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id,lease,'index');
  if j.id is null or (j.content_hash is not null and j.content_hash<>digest) then return false; end if;
  update public.processing_jobs set content_hash=digest,pages=source_pages where id=j.id;
  insert into public.processing_jobs(kind,document_id,generation,content_hash,pages,encrypted_key,use_ocr)
    values('summary',j.document_id,j.generation,digest,source_pages,j.encrypted_key,j.use_ocr)
    on conflict (document_id,kind,generation) do nothing;
  if found then
    update public.documents set summary_status='pending',summary_stage='Course Map queued',summary_error=null where id=j.document_id;
  end if;
  return true;
end;
$$;

-- Document and model requests share limits across all application instances.
create table public.study_request_limits (
  owner_id uuid not null references auth.users on delete cascade,
  operation text not null,
  window_start timestamptz not null,
  used integer not null check (used > 0),
  primary key (owner_id,operation)
);
alter table public.study_request_limits enable row level security;
revoke all on public.study_request_limits from public, anon, authenticated;
grant all on public.study_request_limits to service_role;

create function public.consume_study_quota(owner uuid, operation_name text)
returns boolean language plpgsql set search_path = '' as $$
declare max_count integer; duration interval; recorded integer; now_at timestamptz := clock_timestamp();
begin
  select limits.maximum,limits.period into max_count,duration
    from (values ('socratic',20,interval '1 minute'),('explain',6,interval '1 minute'),
      ('exercise',5,interval '1 minute'),('correction',8,interval '1 minute'),
      ('exam_generation',6,interval '1 hour'),('exam_grading',12,interval '1 hour'),
      ('pdf_retry',12,interval '1 hour'),('pdf_ocr',4,interval '1 hour')) as limits(name,maximum,period)
    where name=operation_name;
  if max_count is null then return false; end if;
  insert into public.study_request_limits as q(owner_id,operation,window_start,used)
    values(owner,operation_name,now_at,1)
    on conflict(owner_id,operation) do update
      set window_start=case when q.window_start <= now_at-duration then now_at else q.window_start end,
          used=case when q.window_start <= now_at-duration then 1 else q.used+1 end
    where q.window_start <= now_at-duration or q.used < max_count returning used into recorded;
  return recorded is not null;
end;
$$;

revoke execute on function public.consume_study_quota(uuid,text),
  public.match_embeddings(extensions.vector,integer,uuid) from public, anon, authenticated;
grant execute on function public.consume_study_quota(uuid,text),
  public.match_embeddings(extensions.vector,integer,uuid) to service_role;

-- Browser code reads owned records through RLS. Server code owns model outputs.
revoke insert, update, delete on public.student_profiles, public.diagnostics, public.key_terms from public, anon, authenticated;
grant select, insert, update, delete on public.student_profiles, public.diagnostics, public.key_terms to service_role;

-- Keep a cleanup record when a document is removed, including course cascades.
create table public.deleted_pdf_objects (
  storage_path text primary key,
  created_at timestamptz not null default now()
);
alter table public.deleted_pdf_objects enable row level security;
revoke all on public.deleted_pdf_objects from public, anon, authenticated;
grant select,insert,delete on public.deleted_pdf_objects to service_role;

create schema if not exists socra_private;
revoke all on schema socra_private from public, anon, authenticated;

create function socra_private.record_deleted_pdf_object()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  if split_part(old.storage_path,'/',2)=old.course_id::text
     and split_part(old.storage_path,'/',1) ~ '^[0-9a-f-]{36}$'
     and split_part(old.storage_path,'/',3) <> '' then
    insert into public.deleted_pdf_objects(storage_path) values(old.storage_path) on conflict do nothing;
  end if;
  return old;
end;
$$;
revoke execute on function socra_private.record_deleted_pdf_object() from public, anon, authenticated;
create trigger document_storage_cleanup after delete on public.documents
  for each row execute function socra_private.record_deleted_pdf_object();

-- Only checked API handlers can publish saved cards and source provenance.
revoke insert on public.library_items, public.notebook_notes from public, anon, authenticated;
revoke update on public.notebook_notes from public, anon, authenticated;
grant update (title, topic, content, updated_at) on public.notebook_notes to authenticated;
grant insert on public.library_items, public.notebook_notes to service_role;
