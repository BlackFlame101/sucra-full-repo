-- Disable the Unit Map flag and stop its workers before running this rollback.
-- This deletes Unit Map rows and jobs. Index and summary jobs are preserved.
begin;

lock table public.processing_jobs in access exclusive mode;

drop function if exists public.retry_failed_explain_unit_map(uuid);
drop function if exists public.fail_explain_unit_map(uuid,uuid,boolean);
drop function if exists public.publish_explain_unit_map(uuid,uuid,jsonb,text);
drop function if exists public.reuse_pdf_index_with_unit_map(uuid,uuid,text,integer,text,text);
drop function if exists public.activate_pdf_index_with_unit_map(uuid,uuid,text,integer,jsonb,text,text);
drop function if exists public.backfill_explain_unit_maps(integer,text);
drop function if exists public.queue_explain_unit_map(uuid,integer,uuid,text,jsonb);

delete from public.processing_jobs where kind = 'unit_map';
alter table public.processing_jobs drop constraint if exists processing_jobs_kind_check;
alter table public.processing_jobs add constraint processing_jobs_kind_check
  check (kind in ('index', 'summary'));

drop table if exists public.explain_unit_maps;

create or replace function public.pdf_processing_available(owner uuid)
returns boolean language sql set search_path = '' as $$
  select coalesce(sum(case when j.kind = 'index' and not exists (
    select from public.processing_jobs child where child.document_id = j.document_id
       and child.generation = j.generation and child.kind = 'summary'
  ) then 2 else 1 end),0) <= 10 from public.processing_jobs j
  join public.documents d on d.id = j.document_id
  join public.courses c on c.id = d.course_id
  where c.user_id = owner and j.status in ('queued','running');
$$;

commit;
