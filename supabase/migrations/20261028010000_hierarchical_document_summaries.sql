-- Hierarchical summaries are private derived data, tied to an immutable PDF hash.
alter table public.documents add column if not exists content_hash text;
alter table public.documents add column if not exists summary_status text not null default 'pending'
  check (summary_status in ('pending', 'processing', 'ready', 'failed', 'not_applicable'));

create table if not exists public.document_summaries (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  document_version text not null,
  level text not null check (level in ('document', 'section')),
  section_index integer,
  title text not null,
  summary text not null,
  page_start integer not null check (page_start >= 1),
  page_end integer not null check (page_end >= page_start),
  created_at timestamptz not null default now(),
  unique(document_id, document_version, level, section_index)
);

create index if not exists document_summaries_course_version_idx
  on public.document_summaries(course_id, document_version, level);
create index if not exists document_summaries_document_idx
  on public.document_summaries(document_id);
alter table public.document_summaries enable row level security;
drop policy if exists "deny browser access to document summaries" on public.document_summaries;
create policy "deny browser access to document summaries"
  on public.document_summaries for all to anon, authenticated using (false) with check (false);
