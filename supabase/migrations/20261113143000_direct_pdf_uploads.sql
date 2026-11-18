-- The app controls destinations. Existing PDFs remain readable by their owners.
create policy socra_documents_server_insert on storage.objects as restrictive for insert to anon, authenticated
  with check (bucket_id <> 'documents');
create policy socra_documents_server_update on storage.objects as restrictive for update to anon, authenticated
  using (bucket_id <> 'documents') with check (bucket_id <> 'documents');
create policy socra_documents_server_delete on storage.objects as restrictive for delete to anon, authenticated
  using (bucket_id <> 'documents');

create table public.pdf_uploads (
  id uuid primary key,
  owner_id uuid not null,
  course_id uuid not null,
  storage_path text not null unique,
  filename text not null,
  size_bytes integer not null check (size_bytes between 1 and 52428800),
  digest text not null check (digest ~ '^[0-9a-f]{64}$'),
  created_at timestamptz not null default now(),
  cleanup_after timestamptz not null default now() + interval '51 hours',
  status text not null default 'pending' check (status in ('pending','finished','cancelled'))
);
create index pdf_uploads_owner_time on public.pdf_uploads(owner_id, created_at desc);
create index pdf_uploads_cleanup on public.pdf_uploads(cleanup_after);
alter table public.pdf_uploads enable row level security;
revoke all on public.pdf_uploads from public, anon, authenticated;
grant all on public.pdf_uploads to service_role;
grant select on storage.objects to service_role;

create function public.reserve_pdf_upload(
  owner uuid, course uuid, upload_id uuid, filename_arg text, size_arg integer, digest_arg text
) returns jsonb language plpgsql set search_path = '' as $$
declare u public.pdf_uploads;
begin
  if not exists (select from public.courses c where c.id = course and c.user_id = owner) then
    return jsonb_build_object('state','missing');
  end if;
  if size_arg is null or size_arg not between 1 and 52428800 or digest_arg is null
     or digest_arg !~ '^[0-9a-f]{64}$' or char_length(coalesce(filename_arg,'')) not between 1 and 255 then
    return jsonb_build_object('state','invalid');
  end if;
  perform pg_advisory_xact_lock(hashtextextended(owner::text, 4321));
  select * into u from public.pdf_uploads where id = upload_id;
  if found then
    if u.owner_id <> owner or u.course_id <> course or u.digest <> digest_arg or u.size_bytes <> size_arg then
      return jsonb_build_object('state','missing');
    end if;
    if u.status = 'pending' and u.created_at <= now() - interval '24 hours' then
      return jsonb_build_object('state','expired');
    end if;
    return jsonb_build_object('state',u.status,'path',u.storage_path);
  end if;
  if exists (select from public.documents where id=upload_id) then
    return jsonb_build_object('state','expired');
  end if;
  if (select count(*) from public.pdf_uploads where owner_id = owner and created_at > now() - interval '24 hours') >= 24
     or (select count(*) from public.pdf_uploads where owner_id = owner and status = 'pending'
         and created_at > now() - interval '24 hours') >= 8 then
    return jsonb_build_object('state','upload_quota');
  end if;
  insert into public.pdf_uploads(id,owner_id,course_id,storage_path,filename,size_bytes,digest)
    values (upload_id,owner,course,owner::text || '/' || course::text || '/' || upload_id::text || '.pdf',
            filename_arg,size_arg,digest_arg) returning * into u;
  return jsonb_build_object('state','pending','path',u.storage_path);
end;
$$;

create function public.pdf_processing_available(owner uuid)
returns boolean language sql set search_path = '' as $$
  select coalesce(sum(case when j.kind = 'index' and not exists (
    select from public.processing_jobs child where child.document_id = j.document_id
       and child.generation = j.generation and child.kind = 'summary'
  ) then 2 else 1 end),0) <= 10 from public.processing_jobs j
  join public.documents d on d.id = j.document_id
  join public.courses c on c.id = d.course_id
  where c.user_id = owner and j.status in ('queued','running');
$$;

create function public.finish_pdf_upload(owner uuid, upload_id uuid, credential text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare u public.pdf_uploads; d jsonb;
begin
  perform pg_advisory_xact_lock(hashtextextended(owner::text, 4321));
  select * into u from public.pdf_uploads where id = upload_id and owner_id = owner for update;
  if not found or not exists (select from public.courses c where c.id = u.course_id and c.user_id = owner) then
    return jsonb_build_object('state','missing');
  end if;
  if u.status = 'finished' then
    select to_jsonb(doc) into d from public.documents doc where doc.id = u.id and doc.course_id = u.course_id;
    if d is null then return jsonb_build_object('state','missing'); end if;
    return jsonb_build_object('state','finished','document',d);
  end if;
  if u.status <> 'pending' or u.created_at <= now() - interval '24 hours' then
    return jsonb_build_object('state','expired');
  end if;
  if not exists (select from storage.objects o where o.bucket_id = 'documents' and o.name = u.storage_path
        and o.metadata->>'size' = u.size_bytes::text and o.metadata->>'mimetype' = 'application/pdf') then
    return jsonb_build_object('state','incomplete');
  end if;
  if not public.pdf_processing_available(owner) then return jsonb_build_object('state','processing_quota'); end if;
  d := public.queue_pdf_upload(owner,u.course_id,u.id,u.filename,u.storage_path,u.size_bytes,u.digest,credential);
  update public.pdf_uploads set status = 'finished' where id = u.id;
  return jsonb_build_object('state','finished','document',d);
end;
$$;

create function public.cancel_pdf_upload(owner uuid, upload_id uuid)
returns boolean language plpgsql set search_path = '' as $$
begin
  update public.pdf_uploads set status = 'cancelled'
    where id = upload_id and owner_id = owner and status = 'pending';
  return found;
end;
$$;

create function public.retry_pdf_with_quota(owner uuid, document uuid, job_kind text, credential text default null)
returns jsonb language plpgsql set search_path = '' as $$
declare d jsonb;
begin
  perform pg_advisory_xact_lock(hashtextextended(owner::text, 4321));
  if not public.pdf_processing_available(owner) then return jsonb_build_object('state','processing_quota'); end if;
  d := public.queue_pdf_retry(owner, document, job_kind, credential);
  return jsonb_build_object('state',case when d is null then 'unavailable' else 'queued' end,'document',d);
end;
$$;

alter table public.documents add column index_config text, add column index_chunk_count integer;
create index documents_pdf_reuse on public.documents(content_hash,index_config,course_id)
  where index_status = 'ready' and index_config is not null;

-- Record the cache key in the same transaction that publishes the vector set.
create function public.activate_versioned_pdf_index(
  job_id uuid, lease uuid, digest text, page_total integer, chunks jsonb, config_key text
) returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id, lease, 'index');
  if j.id is null then return false; end if;
  if not public.activate_document_index(job_id,lease,digest,page_total,chunks) then return false; end if;
  update public.documents set index_config = config_key, index_chunk_count = jsonb_array_length(chunks)
    where id = j.document_id;
  return true;
end;
$$;

create function public.reuse_pdf_index(
  job_id uuid, lease uuid, digest text, page_total integer, config_key text
) returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs; target public.documents; source public.documents; copied integer;
begin
  j := public.lock_pdf_job(job_id, lease, 'index');
  if j.id is null or j.content_hash is distinct from digest then return false; end if;
  select * into target from public.documents where id = j.document_id;
  if target.index_status = 'ready' then return false; end if;
  select d.* into source from public.documents d
    join public.courses c on c.id = d.course_id
    join public.courses owner_course on owner_course.id = target.course_id and owner_course.user_id = c.user_id
    where d.id <> target.id and d.index_status = 'ready' and d.content_hash = digest
      and d.index_config = config_key and d.page_count = page_total and d.index_chunk_count > 0
    order by d.id limit 1 for share of d skip locked;
  if not found then return false; end if;
  if (select count(*) from public.embeddings where document_id = source.id) <> source.index_chunk_count then
    return false;
  end if;
  delete from public.embeddings where document_id = target.id;
  insert into public.embeddings(document_id,content,embedding,page_number,chunk_index,metadata)
    select target.id,e.content,e.embedding,e.page_number,e.chunk_index,
      jsonb_build_object('filename',target.filename,'course_id',target.course_id)
    from public.embeddings e where e.document_id = source.id;
  get diagnostics copied = row_count;
  if copied <> source.index_chunk_count then raise exception 'PDF index changed while copying'; end if;
  update public.documents set content_hash = digest, page_count = page_total, index_status = 'ready',
    index_stage = null, processing_error = null, index_config = config_key, index_chunk_count = copied where id = target.id;
  update public.processing_jobs set status = 'ready', lease_token = null, lease_until = null,
    pages = null, encrypted_key = null where id = j.id;
  return true;
end;
$$;

revoke execute on function public.reserve_pdf_upload(uuid,uuid,uuid,text,integer,text),
  public.pdf_processing_available(uuid), public.finish_pdf_upload(uuid,uuid,text), public.cancel_pdf_upload(uuid,uuid),
  public.retry_pdf_with_quota(uuid,uuid,text,text), public.activate_versioned_pdf_index(uuid,uuid,text,integer,jsonb,text),
  public.reuse_pdf_index(uuid,uuid,text,integer,text) from public, anon, authenticated;
grant execute on function public.reserve_pdf_upload(uuid,uuid,uuid,text,integer,text),
  public.pdf_processing_available(uuid), public.finish_pdf_upload(uuid,uuid,text), public.cancel_pdf_upload(uuid,uuid),
  public.retry_pdf_with_quota(uuid,uuid,text,text), public.activate_versioned_pdf_index(uuid,uuid,text,integer,jsonb,text),
  public.reuse_pdf_index(uuid,uuid,text,integer,text) to service_role;
