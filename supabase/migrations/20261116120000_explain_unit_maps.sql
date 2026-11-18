begin;

alter table public.processing_jobs drop constraint processing_jobs_kind_check;
alter table public.processing_jobs add constraint processing_jobs_kind_check
  check (kind in ('index', 'summary', 'unit_map'));

create table public.explain_unit_maps (
  document_id uuid primary key references public.documents on delete cascade,
  generation integer not null,
  source_hash text not null,
  extractor_version text not null,
  text_hash text not null,
  units jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.explain_unit_maps enable row level security;
revoke all on public.explain_unit_maps from public, anon, authenticated;
grant select, insert, update on public.explain_unit_maps to service_role;

create function public.queue_explain_unit_map(
  doc_id uuid, expected_generation integer, owner_id uuid, extractor_version text, source_pages jsonb default null
) returns boolean language plpgsql set search_path = '' as $$
declare d public.documents;
begin
  select doc.* into d from public.documents doc join public.courses c on c.id = doc.course_id
    where doc.id = doc_id and doc.index_generation = expected_generation
      and doc.index_status = 'ready' and doc.index_stage is null and doc.content_hash is not null
      and (owner_id is null or c.user_id = owner_id)
    for update of doc;
  if not found then return false; end if;
  if exists (select 1 from public.processing_jobs j where j.document_id = doc_id
             and j.generation = expected_generation and j.kind = 'index' and j.status <> 'ready')
    then return false; end if;
  if exists (select 1 from public.explain_unit_maps m where m.document_id = doc_id
             and m.generation = expected_generation and m.source_hash = d.content_hash
             and m.extractor_version = queue_explain_unit_map.extractor_version) then return true; end if;
  insert into public.processing_jobs(kind, document_id, generation, content_hash, pages, use_ocr)
    values ('unit_map', doc_id, expected_generation, d.content_hash, source_pages,
            coalesce(d.index_config like '%:ocr-tesseract-v1:%', false))
    on conflict (document_id, kind, generation) do update
      set status = 'queued', attempts = 0, available_at = now(),
          content_hash = excluded.content_hash, pages = excluded.pages, use_ocr = excluded.use_ocr,
          lease_token = null, lease_until = null
      where processing_jobs.status = 'ready';
  return found;
end;
$$;

create function public.backfill_explain_unit_maps(batch_size integer, extractor_version text)
returns integer language plpgsql set search_path = '' as $$
declare d record; queued integer := 0;
begin
  for d in
    select doc.id, doc.index_generation from public.documents doc
    where doc.index_status = 'ready' and doc.index_stage is null and doc.content_hash is not null
      and not exists (
        select 1 from public.explain_unit_maps m where m.document_id = doc.id
          and m.generation = doc.index_generation and m.source_hash = doc.content_hash
          and m.extractor_version = backfill_explain_unit_maps.extractor_version)
      and not exists (
        select 1 from public.processing_jobs j where j.document_id = doc.id and j.generation = doc.index_generation
          and ((j.kind = 'unit_map' and j.status <> 'ready') or (j.kind = 'index' and j.status <> 'ready')))
    order by doc.id limit greatest(0, least(coalesce(batch_size, 0), 100)) for update skip locked
  loop
    if public.queue_explain_unit_map(d.id, d.index_generation, null, extractor_version)
      then queued := queued + 1; end if;
  end loop;
  return queued;
end;
$$;

-- Queue in the index publication transaction, while the generation lock is held.
create function public.activate_pdf_index_with_unit_map(
  job_id uuid, lease uuid, digest text, page_total integer, chunks jsonb, config_key text, extractor_version text
) returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id, lease, 'index');
  if j.id is null or not public.activate_versioned_pdf_index(job_id, lease, digest, page_total, chunks, config_key)
    then return false; end if;
  begin
    perform public.queue_explain_unit_map(j.document_id, j.generation, null, extractor_version,
      case when j.use_ocr then j.pages else null end);
  exception when others then
    raise warning 'Unit Map enqueue after index activation failed for document % (SQLSTATE %)', j.document_id, SQLSTATE;
  end;
  return true;
end;
$$;

create function public.reuse_pdf_index_with_unit_map(
  job_id uuid, lease uuid, digest text, page_total integer, config_key text, extractor_version text
) returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id, lease, 'index');
  if j.id is null or not public.reuse_pdf_index(job_id, lease, digest, page_total, config_key)
    then return false; end if;
  begin
    perform public.queue_explain_unit_map(j.document_id, j.generation, null, extractor_version,
      case when j.use_ocr then j.pages else null end);
  exception when others then
    raise warning 'Unit Map enqueue after index reuse failed for document % (SQLSTATE %)', j.document_id, SQLSTATE;
  end;
  return true;
end;
$$;

create function public.publish_explain_unit_map(job_id uuid, lease uuid, skeleton jsonb, extractor_version text)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  if jsonb_typeof(skeleton->'units') is distinct from 'array'
     or skeleton->>'extractor_version' is distinct from extractor_version
     or coalesce(skeleton->>'text_hash', '') !~ '[^[:space:]]'
     or nullif(btrim(extractor_version), '') is null then
    raise exception 'Invalid Unit Map skeleton or extractor version' using errcode = '22023';
  end if;
  j := public.lock_pdf_job(job_id, lease, 'unit_map');
  if j.id is null or not exists (
    select 1 from public.documents d where d.id = j.document_id and d.index_status = 'ready'
      and d.index_generation = j.generation and d.content_hash = j.content_hash
  ) then return false; end if;
  insert into public.explain_unit_maps(document_id, generation, source_hash, extractor_version, text_hash, units)
    values (j.document_id, j.generation, j.content_hash, publish_explain_unit_map.extractor_version,
            skeleton->>'text_hash', skeleton->'units')
    on conflict (document_id) do update set generation = excluded.generation,
      source_hash = excluded.source_hash, extractor_version = excluded.extractor_version,
      text_hash = excluded.text_hash, units = excluded.units, updated_at = now()
    where excluded.generation >= explain_unit_maps.generation;
  if not found then
    update public.processing_jobs set status = 'failed', lease_token = null, lease_until = null, pages = null
      where id = j.id;
    return false;
  end if;
  update public.processing_jobs set status = 'ready', lease_token = null, lease_until = null, pages = null
    where id = j.id;
  return true;
end;
$$;

create function public.fail_explain_unit_map(job_id uuid, lease uuid, terminal boolean)
returns boolean language plpgsql set search_path = '' as $$
declare j public.processing_jobs;
begin
  j := public.lock_pdf_job(job_id, lease, 'unit_map');
  if j.id is null then return false; end if;
  update public.processing_jobs
    set status = case when terminal or j.attempts >= 3 then 'failed' else 'queued' end,
        available_at = now() + make_interval(secs => 10 * power(2, least(j.attempts, 3))),
        lease_token = null, lease_until = null,
        pages = case when terminal or j.attempts >= 3 then null else pages end
    where id = j.id;
  return true;
end;
$$;

create function public.retry_failed_explain_unit_map(doc_id uuid)
returns boolean language plpgsql set search_path = '' as $$
declare d public.documents;
begin
  select * into d from public.documents where id = doc_id and index_status = 'ready'
    and index_stage is null for update;
  if not found then return false; end if;
  update public.processing_jobs j
    set status = 'queued', attempts = 0, available_at = now(), lease_token = null, lease_until = null
    where j.document_id = doc_id and j.generation = d.index_generation
      and j.content_hash = d.content_hash and j.kind = 'unit_map' and j.status = 'failed';
  return found;
end;
$$;

revoke execute on function public.queue_explain_unit_map(uuid,integer,uuid,text,jsonb),
  public.backfill_explain_unit_maps(integer,text),
  public.activate_pdf_index_with_unit_map(uuid,uuid,text,integer,jsonb,text,text),
  public.reuse_pdf_index_with_unit_map(uuid,uuid,text,integer,text,text),
  public.publish_explain_unit_map(uuid,uuid,jsonb,text), public.fail_explain_unit_map(uuid,uuid,boolean),
  public.retry_failed_explain_unit_map(uuid)
  from public, anon, authenticated;
grant execute on function public.queue_explain_unit_map(uuid,integer,uuid,text,jsonb),
  public.backfill_explain_unit_maps(integer,text),
  public.activate_pdf_index_with_unit_map(uuid,uuid,text,integer,jsonb,text,text),
  public.reuse_pdf_index_with_unit_map(uuid,uuid,text,integer,text,text),
  public.publish_explain_unit_map(uuid,uuid,jsonb,text), public.fail_explain_unit_map(uuid,uuid,boolean),
  public.retry_failed_explain_unit_map(uuid)
  to service_role;

create or replace function public.pdf_processing_available(owner uuid)
returns boolean language sql set search_path = '' as $$
  select coalesce(sum(case when j.kind = 'index' and not exists (
    select from public.processing_jobs child where child.document_id = j.document_id
       and child.generation = j.generation and child.kind = 'summary'
  ) then 2 else 1 end),0) <= 10 from public.processing_jobs j
  join public.documents d on d.id = j.document_id
  join public.courses c on c.id = d.course_id
  where c.user_id = owner and j.kind in ('index','summary') and j.status in ('queued','running');
$$;

commit;
