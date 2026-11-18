begin;

create table public.notebook_note_revisions (
  note_id uuid not null references public.notebook_notes(id) on delete cascade,
  version integer not null check (version > 0),
  generated_revision_id text not null,
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object'),
  created_at timestamptz not null default now(),
  primary key (note_id, version)
);
alter table public.notebook_note_revisions enable row level security;
revoke all on public.notebook_note_revisions from public, anon, authenticated;
grant select on public.notebook_note_revisions to authenticated;
grant select, insert on public.notebook_note_revisions to service_role;
create policy notebook_note_revisions_read_own on public.notebook_note_revisions
  for select to authenticated using (exists (
    select 1 from public.notebook_notes n
    where n.id = notebook_note_revisions.note_id and n.user_id = (select auth.uid())
  ));

-- Runs inside the existing compare-and-swap write. If snapshotting fails,
-- the editor's update cannot succeed independently of its revision.
create function public.record_educational_note_revision() returns trigger
language plpgsql security invoker set search_path = '' as $$
declare
  generated jsonb := new.source_data->'explanation';
begin
  if generated->>'format' = 'educational_document' and generated->>'schema_version' = '3' then
    insert into public.notebook_note_revisions(note_id, version, generated_revision_id, snapshot)
    values (new.id, new.version, generated->>'revision_id',
            jsonb_build_object('title', new.title, 'topic', new.topic, 'content', new.content,
              'content_json', new.content_json, 'course_id', new.course_id, 'tags', new.tags, 'starred', new.starred))
    on conflict (note_id, version) do nothing;
  end if;
  return new;
end;
$$;
revoke all on function public.record_educational_note_revision() from public, anon, authenticated;
grant execute on function public.record_educational_note_revision() to service_role;
create trigger notebook_educational_note_history
  after insert or update of version, source_data on public.notebook_notes
  for each row execute function public.record_educational_note_revision();

-- Capture the rich nodes with the existing idempotent procedure, then retain
-- their immutable origin in the same transaction. A selection or append uses
-- the ordinary capture path and does not claim to be a complete revision.
create function public.capture_educational_document(
  owner uuid, request uuid, destination uuid, source_course uuid,
  source_session uuid, source_message uuid, source_kind text, source_citations jsonb,
  fingerprint_arg text, note_title text, body_nodes jsonb, body_text text, legacy_nodes jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  generated jsonb;
  captured jsonb;
begin
  if destination is not null or source_kind is distinct from 'explanation' then
    return jsonb_build_object('state', 'missing');
  end if;
  select m.metadata->'explanation' into generated
    from public.messages m join public.sessions s on s.id = m.session_id
    join public.courses c on c.id = s.course_id
    where m.id = source_message and m.role = 'assistant' and s.id = source_session
      and c.id = source_course and c.user_id = owner
      and m.metadata->'explanation'->>'schema_version' = '3'
      and m.metadata->'explanation'->>'format' = 'educational_document';
  if not found then return jsonb_build_object('state', 'missing'); end if;

  captured := public.capture_notebook_response(owner, request, destination, source_course,
    source_session, source_message, source_kind, source_citations,
    fingerprint_arg, note_title, body_nodes, body_text, legacy_nodes);
  if captured->>'state' = 'saved' then
    update public.notebook_notes
      set source_data = source_data || jsonb_build_object('explanation', generated, 'initial_note_version', version,
        'session_id', source_session, 'message_id', source_message)
      where id = (captured->>'id')::uuid and user_id = owner and source_type = 'explanation'
        and source_data->>'capture_fingerprint' = fingerprint_arg and not (source_data ? 'explanation');
  end if;
  return captured;
end;
$$;
revoke all on function public.capture_educational_document(uuid,uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text,jsonb,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.capture_educational_document(uuid,uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text,jsonb,text,jsonb)
  to service_role;

commit;
