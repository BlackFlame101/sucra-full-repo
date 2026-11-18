-- Preserve existing vectors and summaries. New PDFs become ready only at activation.
alter table public.documents
  add column index_status text not null default 'ready' check (index_status in ('pending','extracting','embedding','indexing','ready','failed')),
  add column index_generation integer not null default 0,
  add column index_stage text,
  add column summary_stage text,
  add column processing_error text,
  add column summary_error text;

-- This version starts with PDF work only.
create table public.processing_jobs (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('index','summary')),
  document_id uuid not null references public.documents on delete cascade,
  generation integer not null,
  content_hash text,
  pages jsonb,
  encrypted_key text,
  status text not null default 'queued' check (status in ('queued','running','ready','failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  lease_token uuid,
  lease_until timestamptz,
  created_at timestamptz not null default now(),
  unique (document_id, kind, generation)
);
create index processing_jobs_available_idx on public.processing_jobs (kind, available_at, created_at)
  where status in ('queued', 'running');
alter table public.processing_jobs enable row level security;
revoke all on public.processing_jobs from public, anon, authenticated;
grant all on public.processing_jobs to service_role;

-- Browser ownership policies still protect reads. Only the processing service
-- can assign source paths, change job status, or publish vectors.
revoke insert, update, delete on public.documents, public.embeddings from public, anon, authenticated;
grant select, insert, update, delete on public.documents, public.embeddings, public.document_summaries to service_role;

create function public.queue_pdf_upload(
  owner_id uuid, course uuid, document uuid, filename_arg text,
  path text, size_bytes integer, digest text, credential text default null
)
returns jsonb language plpgsql set search_path = '' as $$
declare d public.documents;
begin
  if not exists (select from public.courses c where c.id = course and c.user_id = owner_id)
    or path <> owner_id::text || '/' || course::text || '/' || document::text || '.pdf'
    or digest is null or digest !~ '^[0-9a-f]{64}$' or size_bytes not between 1 and 52428800 then
    raise exception 'Invalid upload destination';
  end if;
  insert into public.documents(id, course_id, filename, storage_path, file_size, index_status, index_generation, index_stage)
    values (document, course, filename_arg, path, size_bytes, 'pending', 1, 'Queued for indexing')
    on conflict (id) do nothing
    returning * into d;
  if not found then
    select * into d from public.documents where id = document and course_id = course and storage_path = path;
    if not found then raise exception 'Upload identifier unavailable'; end if;
    return to_jsonb(d);
  end if;
  insert into public.processing_jobs(kind, document_id, generation, content_hash, encrypted_key)
    values ('index', d.id, d.index_generation, digest, credential);
  return to_jsonb(d);
end;
$$;

create function public.queue_pdf_retry(owner_id uuid, document uuid, job_kind text, credential text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare d public.documents; j public.processing_jobs;
begin
  select doc.* into d from public.documents doc join public.courses c on c.id = doc.course_id
    where doc.id = document and c.user_id = owner_id for update of doc;
  if not found or split_part(d.storage_path, '/', 1) <> owner_id::text or job_kind not in ('index','summary') then
    return null;
  end if;
  select * into j from public.processing_jobs
    where document_id = d.id and kind = job_kind and generation = d.index_generation;
  if found and j.status in ('queued','running') then return to_jsonb(d); end if;

  if job_kind = 'index' then
    update public.documents set index_generation = index_generation + 1, index_stage = 'Queued for indexing',
      index_status = case when index_status = 'ready' then 'ready' else 'pending' end, processing_error = null,
      summary_status = case when summary_stage is not null then 'pending' else summary_status end,
      summary_stage = null, summary_error = null
      where id = d.id returning * into d;
    -- Remove superseded jobs. Their lease can no longer publish a result.
    delete from public.processing_jobs where document_id = d.id;
    insert into public.processing_jobs(kind, document_id, generation, content_hash, encrypted_key)
      values ('index', d.id, d.index_generation, coalesce(d.content_hash, j.content_hash), credential);
  elsif d.index_status = 'ready' then
    if d.index_stage is not null then return to_jsonb(d); end if;
    update public.documents set summary_status = 'pending', summary_stage = 'Course Map queued', summary_error = null
      where id = d.id returning * into d;
    insert into public.processing_jobs(kind, document_id, generation, content_hash, pages, encrypted_key)
      values ('summary', d.id, d.index_generation, d.content_hash, j.pages, credential)
      on conflict (document_id, kind, generation) do update set
        status = 'queued', available_at = now(), attempts = 0, lease_token = null, lease_until = null,
        encrypted_key = excluded.encrypted_key;
  else
    return null;
  end if;
  return to_jsonb(d);
end;
$$;

create function public.claim_processing_job(job_kind text)
returns setof public.processing_jobs language sql set search_path = '' as $$
  with candidate as (
    select id from public.processing_jobs
    where kind = job_kind
      and ((status = 'queued' and available_at <= now()) or (status = 'running' and lease_until <= now()))
    order by available_at, created_at
    limit 1 for update skip locked
  )
  update public.processing_jobs j set
    status = 'running', attempts = attempts + 1, lease_token = gen_random_uuid(),
    lease_until = now() + interval '5 minutes'
  from candidate where j.id = candidate.id returning j.*;
$$;

-- All writes lock document first, then job. This is also the order used by
-- deletion/cascades, and makes an expired or superseded job unable to publish.
create function public.lock_pdf_job(job_id uuid, lease uuid, job_kind text)
returns public.processing_jobs language plpgsql set search_path = '' as $$
declare j public.processing_jobs; current_generation integer;
begin
  select * into j from public.processing_jobs where id = job_id;
  if not found then return null; end if;
  select index_generation into current_generation from public.documents where id = j.document_id for update;
  if not found or current_generation <> j.generation then return null; end if;
  select * into j from public.processing_jobs
    where id = job_id and lease_token = lease and status = 'running' and lease_until > clock_timestamp()
      and (job_kind is null or kind = job_kind) for update;
  return j;
end;
$$;

create function public.update_pdf_stage(job_id uuid, lease uuid, state text, label text)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id, lease, null);
  if j.id is null then return false; end if;
  if j.kind = 'index' then
    update public.documents set index_stage = label,
      index_status = case when index_status = 'ready' then 'ready' else state end where id = j.document_id;
  else
    update public.documents set summary_stage = label, summary_status = 'processing' where id = j.document_id;
  end if;
  return true;
end;
$$;

create function public.publish_pdf_pages(job_id uuid, lease uuid, digest text, source_pages jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id, lease, 'index');
  if j.id is null or (j.content_hash is not null and j.content_hash <> digest) then return false; end if;
  update public.processing_jobs set content_hash = digest, pages = source_pages where id = j.id;
  insert into public.processing_jobs(kind, document_id, generation, content_hash, pages, encrypted_key)
    values ('summary', j.document_id, j.generation, digest, source_pages, j.encrypted_key)
    on conflict (document_id, kind, generation) do nothing;
  if found then
    update public.documents set summary_status = 'pending', summary_stage = 'Course Map queued', summary_error = null
      where id = j.document_id;
  end if;
  return true;
end;
$$;

create function public.activate_document_index(job_id uuid, lease uuid, digest text, page_total integer, chunks jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs; d public.documents;
begin
  j := public.lock_pdf_job(job_id, lease, 'index');
  if j.id is null or j.content_hash is distinct from digest then return false; end if;
  select * into d from public.documents where id = j.document_id;
  if jsonb_typeof(chunks) <> 'array' or jsonb_array_length(chunks) = 0 or page_total < 1 then
    raise exception 'An empty document cannot be indexed';
  end if;
  delete from public.embeddings where document_id = d.id;
  insert into public.embeddings(document_id, content, embedding, page_number, chunk_index, metadata)
    select d.id, content, embedding::extensions.vector(768), page_number, chunk_index,
      jsonb_build_object('filename', d.filename, 'course_id', d.course_id)
    from jsonb_to_recordset(chunks) as c(content text, embedding text, page_number integer, chunk_index integer);
  update public.documents set content_hash = digest, page_count = page_total, index_status = 'ready',
    index_stage = null, processing_error = null where id = d.id;
  update public.processing_jobs set status = 'ready', lease_token = null, lease_until = null,
    pages = null, encrypted_key = null where id = j.id;
  return true;
end;
$$;

create function public.activate_document_summary(job_id uuid, lease uuid, digest text, summaries jsonb)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs; d public.documents;
begin
  j := public.lock_pdf_job(job_id, lease, 'summary');
  if j.id is null or (j.content_hash is not null and j.content_hash <> digest) then return false; end if;
  select * into d from public.documents where id = j.document_id;
  if d.content_hash is not null and d.content_hash <> digest then return false; end if;
  delete from public.document_summaries where document_id = d.id;
  insert into public.document_summaries(document_id, course_id, document_version, level, section_index, title, summary, page_start, page_end)
    select d.id, d.course_id, digest, level, section_index, title, summary, page_start, page_end
    from jsonb_to_recordset(summaries) as s(level text, section_index integer, title text, summary text, page_start integer, page_end integer);
  update public.documents set summary_status = 'ready', summary_stage = null, summary_error = null,
    content_hash = case when index_status = 'ready' then coalesce(content_hash, digest) else content_hash end
    where id = d.id;
  update public.processing_jobs set status = 'ready', lease_token = null, lease_until = null,
    pages = null, encrypted_key = null where id = j.id;
  return true;
end;
$$;

create function public.fail_pdf_job(job_id uuid, lease uuid, message text, terminal boolean)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs; exhausted boolean; next_label text;
begin
  j := public.lock_pdf_job(job_id, lease, null);
  if j.id is null then return false; end if;
  exhausted := terminal or j.attempts >= 3;
  next_label := case when exhausted then null else 'Waiting to retry' end;
  update public.processing_jobs set status = case when exhausted then 'failed' else 'queued' end,
    available_at = now() + make_interval(secs => 10 * power(2, least(j.attempts, 3))),
    lease_token = null, lease_until = null, encrypted_key = case when exhausted then null else encrypted_key end,
    pages = case when exhausted and j.kind = 'index' then null else pages end where id = j.id;
  if j.kind = 'index' then
    update public.documents set index_stage = next_label, processing_error = case when exhausted then message else null end,
      index_status = case when index_status = 'ready' then 'ready' when exhausted then 'failed' else 'pending' end
      where id = j.document_id;
  else
    update public.documents set summary_stage = next_label, summary_error = case when exhausted then message else null end,
      summary_status = case when exhausted then 'failed' else 'pending' end where id = j.document_id;
  end if;
  return true;
end;
$$;

-- Keep the existing API and RLS behavior. Unpublished documents have no vectors
-- but the explicit status check also protects readiness in legacy callers.
create or replace function public.match_embeddings(
  query_embedding extensions.vector, match_count integer default 5, filter_course_id uuid default null
) returns table(id uuid, content text, document_id uuid, page_number integer, chunk_index integer, filename text, similarity double precision)
language sql stable set search_path = extensions as $$
  select e.id, e.content, e.document_id, e.page_number, e.chunk_index, d.filename, 1 - (e.embedding <=> query_embedding)
  from public.embeddings e join public.documents d on e.document_id = d.id
  where d.index_status = 'ready' and (filter_course_id is null or d.course_id = filter_course_id)
  order by e.embedding <=> query_embedding limit match_count;
$$;

revoke execute on function public.queue_pdf_upload(uuid,uuid,uuid,text,text,integer,text,text),
  public.queue_pdf_retry(uuid,uuid,text,text), public.claim_processing_job(text), public.lock_pdf_job(uuid,uuid,text),
  public.update_pdf_stage(uuid,uuid,text,text), public.publish_pdf_pages(uuid,uuid,text,jsonb),
  public.activate_document_index(uuid,uuid,text,integer,jsonb), public.activate_document_summary(uuid,uuid,text,jsonb),
  public.fail_pdf_job(uuid,uuid,text,boolean) from public, anon, authenticated;
grant execute on function public.queue_pdf_upload(uuid,uuid,uuid,text,text,integer,text,text),
  public.queue_pdf_retry(uuid,uuid,text,text), public.claim_processing_job(text), public.lock_pdf_job(uuid,uuid,text),
  public.update_pdf_stage(uuid,uuid,text,text), public.publish_pdf_pages(uuid,uuid,text,jsonb),
  public.activate_document_index(uuid,uuid,text,integer,jsonb), public.activate_document_summary(uuid,uuid,text,jsonb),
  public.fail_pdf_job(uuid,uuid,text,boolean) to service_role;
