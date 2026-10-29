create table if not exists public.library_items (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  course_id uuid not null references public.courses(id) on delete cascade,
  item_type text not null check (item_type in ('explanation', 'exercise')),
  title text not null check (char_length(title) between 1 and 240),
  content jsonb not null default '{}'::jsonb,
  source_document_id uuid references public.documents(id) on delete set null,
  source_page integer check (source_page is null or source_page > 0),
  created_at timestamptz not null default now()
);

create index if not exists library_items_user_created_idx
  on public.library_items (user_id, created_at desc);
create index if not exists library_items_course_idx
  on public.library_items (course_id);

alter table public.library_items enable row level security;
revoke all on public.library_items from anon, authenticated;
grant select, insert, delete on public.library_items to authenticated;
grant all on public.library_items to service_role;

create policy library_items_select_own
  on public.library_items for select to authenticated
  using ((select auth.uid()) = user_id);
create policy library_items_insert_own
  on public.library_items for insert to authenticated
  with check (
    (select auth.uid()) = user_id
    and exists (
      select 1 from public.courses c
      where c.id = course_id and c.user_id = (select auth.uid())
    )
  );
create policy library_items_delete_own
  on public.library_items for delete to authenticated
  using ((select auth.uid()) = user_id);

create table if not exists public.notebook_notes (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  course_id uuid references public.courses(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 240),
  topic text not null default '',
  content text not null default '',
  source_type text not null default 'manual' check (source_type in ('manual', 'explanation', 'exercise')),
  source_data jsonb not null default '{}'::jsonb,
  source_document_id uuid references public.documents(id) on delete set null,
  source_page integer check (source_page is null or source_page > 0),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists notebook_notes_user_updated_idx
  on public.notebook_notes (user_id, updated_at desc);
create index if not exists notebook_notes_course_idx
  on public.notebook_notes (course_id);

alter table public.notebook_notes enable row level security;
revoke all on public.notebook_notes from anon, authenticated;
grant select, insert, update, delete on public.notebook_notes to authenticated;
grant all on public.notebook_notes to service_role;

create policy notebook_notes_select_own
  on public.notebook_notes for select to authenticated
  using ((select auth.uid()) = user_id);
create policy notebook_notes_insert_own
  on public.notebook_notes for insert to authenticated
  with check (
    (select auth.uid()) = user_id
    and (
      course_id is null or exists (
        select 1 from public.courses c
        where c.id = course_id and c.user_id = (select auth.uid())
      )
    )
  );
create policy notebook_notes_update_own
  on public.notebook_notes for update to authenticated
  using ((select auth.uid()) = user_id)
  with check (
    (select auth.uid()) = user_id
    and (
      course_id is null or exists (
        select 1 from public.courses c
        where c.id = course_id and c.user_id = (select auth.uid())
      )
    )
  );
create policy notebook_notes_delete_own
  on public.notebook_notes for delete to authenticated
  using ((select auth.uid()) = user_id);
