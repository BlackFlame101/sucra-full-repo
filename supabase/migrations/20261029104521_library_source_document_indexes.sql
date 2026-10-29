create index if not exists library_items_source_document_idx
  on public.library_items (source_document_id)
  where source_document_id is not null;

create index if not exists notebook_notes_source_document_idx
  on public.notebook_notes (source_document_id)
  where source_document_id is not null;
