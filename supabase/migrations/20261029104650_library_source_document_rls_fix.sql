drop policy if exists library_items_insert_own on public.library_items;
create policy library_items_insert_own
  on public.library_items for insert to authenticated
  with check (
    (select auth.uid()) = library_items.user_id
    and exists (
      select 1 from public.courses c
      where c.id = library_items.course_id and c.user_id = (select auth.uid())
    )
    and (
      library_items.source_document_id is null or exists (
        select 1 from public.documents d
        where d.id = library_items.source_document_id
          and d.course_id = library_items.course_id
      )
    )
  );

drop policy if exists notebook_notes_insert_own on public.notebook_notes;
create policy notebook_notes_insert_own
  on public.notebook_notes for insert to authenticated
  with check (
    (select auth.uid()) = notebook_notes.user_id
    and (
      notebook_notes.course_id is null or exists (
        select 1 from public.courses c
        where c.id = notebook_notes.course_id and c.user_id = (select auth.uid())
      )
    )
    and (
      notebook_notes.source_document_id is null or exists (
        select 1 from public.documents d
        where d.id = notebook_notes.source_document_id
          and d.course_id = notebook_notes.course_id
      )
    )
  );

drop policy if exists notebook_notes_update_own on public.notebook_notes;
create policy notebook_notes_update_own
  on public.notebook_notes for update to authenticated
  using ((select auth.uid()) = notebook_notes.user_id)
  with check (
    (select auth.uid()) = notebook_notes.user_id
    and (
      notebook_notes.course_id is null or exists (
        select 1 from public.courses c
        where c.id = notebook_notes.course_id and c.user_id = (select auth.uid())
      )
    )
    and (
      notebook_notes.source_document_id is null or exists (
        select 1 from public.documents d
        where d.id = notebook_notes.source_document_id
          and d.course_id = notebook_notes.course_id
      )
    )
  );
