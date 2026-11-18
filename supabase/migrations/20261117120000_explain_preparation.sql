begin;

create table public.explain_preparation_jobs (
  id bigint generated always as identity primary key,
  document_id uuid not null references public.documents on delete cascade,
  generation integer not null,
  source_hash text not null,
  unit_id text not null,
  content_version text not null,
  prompt_version text not null,
  step text not null default 'enrich' check (step = 'enrich'),
  state text not null default 'pending' check (state in ('pending','running','done','failed')),
  attempts integer not null default 0,
  available_at timestamptz not null default now(),
  lease_token uuid,
  lease_until timestamptz,
  result jsonb,
  unique (document_id, generation, unit_id, content_version, prompt_version, step)
);
create index explain_preparation_poll on public.explain_preparation_jobs (available_at, id)
  where state in ('pending','running');
alter table public.explain_preparation_jobs enable row level security;
revoke all on public.explain_preparation_jobs from public, anon, authenticated;
grant select, insert, update on public.explain_preparation_jobs to service_role;
grant usage on sequence public.explain_preparation_jobs_id_seq to service_role;

create function public.request_explain_preparation(
  doc_id uuid, owner_id uuid, expected_generation integer, unit_ids text[], version text
) returns integer language plpgsql set search_path = '' as $$
declare queued integer;
begin
  if cardinality(unit_ids) not between 1 and 5 or nullif(btrim(version), '') is null then return 0; end if;
  insert into public.explain_preparation_jobs(document_id,generation,source_hash,unit_id,content_version,prompt_version)
    select d.id,d.index_generation,d.content_hash,u->>'logical_id',u->>'content_version',version
    from public.documents d join public.courses c on c.id=d.course_id
    join public.explain_unit_maps m on m.document_id=d.id and m.generation=d.index_generation
      and m.source_hash=d.content_hash
    cross join lateral jsonb_array_elements(m.units) u
    where d.id=doc_id and c.user_id=owner_id and d.index_generation=expected_generation
      and d.index_status='ready' and d.index_stage is null and u->>'logical_id'=any(unit_ids)
      and u->>'kind' not in ('transition','front_matter','summary','non_teaching')
    on conflict do nothing;
  get diagnostics queued = row_count;
  return queued;
end;
$$;

create function public.claim_explain_preparation(version text)
returns setof public.explain_preparation_jobs language sql set search_path = '' as $$
  with expired as (
    update public.explain_preparation_jobs j set state='failed',lease_token=null,lease_until=null
    where j.state='running' and j.lease_until<=now() and j.attempts>=3
  ), eligible as (
    select j.id,j.document_id,j.generation,j.available_at
    from public.explain_preparation_jobs j join public.documents d on d.id=j.document_id
    where j.prompt_version=version and j.attempts<3 and j.available_at<=now()
      and d.index_generation=j.generation and d.content_hash=j.source_hash
      and d.index_status='ready' and d.index_stage is null
      and (j.state='pending' or (j.state='running' and j.lease_until<=now()))
  ), first_doc as (
    select document_id,generation from eligible order by available_at,id limit 1
  ), batch as (
    select j.id from public.explain_preparation_jobs j join eligible e on e.id=j.id
      join first_doc f on f.document_id=e.document_id and f.generation=e.generation
    where j.attempts<3 and (j.state='pending' or (j.state='running' and j.lease_until<=now()))
    order by j.available_at,j.id limit 5 for update of j skip locked
  )
  update public.explain_preparation_jobs j set state='running',attempts=j.attempts+1,
    lease_token=gen_random_uuid(),lease_until=now()+interval '5 minutes'
    from batch where j.id=batch.id returning j.*;
$$;

create function public.finish_explain_preparation(job_id bigint, lease uuid, evidence jsonb, failed boolean default false)
returns boolean language plpgsql set search_path = '' as $$
begin
  update public.explain_preparation_jobs j set
    state=case when not failed and evidence is null then 'running' when not failed then 'done'
               when j.attempts>=3 then 'failed' else 'pending' end,
    lease_token=case when not failed and evidence is null then lease else null end,
    lease_until=case when not failed and evidence is null then clock_timestamp()+interval '5 minutes' else null end,
    available_at=case when failed then now()+make_interval(secs=>10*power(2,least(j.attempts,3))::integer)
                      else j.available_at end,
    result=case when not failed and evidence is not null then evidence else null end
  from public.documents d
  where j.id=job_id and j.lease_token=lease and j.lease_until>clock_timestamp() and j.state='running'
    and d.id=j.document_id and d.index_generation=j.generation and d.content_hash=j.source_hash
    and d.index_status='ready' and d.index_stage is null
    and exists (
      select from public.explain_unit_maps m cross join lateral jsonb_array_elements(m.units) u
      where m.document_id=j.document_id and m.generation=j.generation and m.source_hash=j.source_hash
        and u->>'logical_id'=j.unit_id and u->>'content_version'=j.content_version
    )
    and (failed or evidence is null or (
      evidence->>'unit_id'=j.unit_id and evidence->>'content_version'=j.content_version
      and jsonb_typeof(evidence->'checklist')='array'));
  return found;
end;
$$;

revoke execute on function public.request_explain_preparation(uuid,uuid,integer,text[],text),
  public.claim_explain_preparation(text),public.finish_explain_preparation(bigint,uuid,jsonb,boolean)
  from public, anon, authenticated;
grant execute on function public.request_explain_preparation(uuid,uuid,integer,text[],text),
  public.claim_explain_preparation(text),public.finish_explain_preparation(bigint,uuid,jsonb,boolean)
  to service_role;

commit;
