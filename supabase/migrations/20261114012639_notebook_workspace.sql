-- Leave legacy plain text and provenance intact. Rich content is written lazily.
alter table public.notebook_notes
  add column content_json jsonb check (content_json is null or ((
    jsonb_typeof(content_json) = 'object' and content_json->>'type' = 'doc'
    and jsonb_typeof(content_json->'content') = 'array') is true)),
  add column tags text[] not null default '{}' check (cardinality(tags) <= 20),
  add column starred boolean not null default false,
  add column version integer not null default 1 check (version > 0);

-- Notes remain accessible as personal notes if the associated course is deleted.
alter table public.notebook_notes drop constraint notebook_notes_course_id_fkey,
  add constraint notebook_notes_course_id_fkey foreign key (course_id) references public.courses(id) on delete set null;

-- Every write must go through the version-checked API. Reads and owner deletes
-- continue to use the existing RLS policies.
revoke update (title, topic, content, updated_at) on public.notebook_notes from authenticated;
grant select, insert, update on public.notebook_notes to service_role;

create table public.notebook_sources (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  note_id uuid not null references public.notebook_notes(id) on delete cascade,
  course_id uuid references public.courses(id) on delete set null,
  session_id uuid references public.sessions(id) on delete set null,
  message_id uuid references public.messages(id) on delete set null,
  kind text not null check (kind in ('explanation', 'exercise', 'tutor')),
  citations jsonb not null default '[]' check (jsonb_typeof(citations) = 'array'),
  fingerprint text not null check (char_length(fingerprint) = 64),
  created_at timestamptz not null default now()
);
create index notebook_sources_note_idx on public.notebook_sources(note_id);
create unique index notebook_sources_note_fingerprint_idx on public.notebook_sources(note_id, fingerprint);
create index notebook_sources_course_idx on public.notebook_sources(course_id);
create index notebook_sources_session_idx on public.notebook_sources(session_id);
create index notebook_sources_message_idx on public.notebook_sources(message_id);
alter table public.notebook_sources enable row level security;
revoke all on public.notebook_sources from public, anon, authenticated;
grant select, insert on public.notebook_sources to service_role;

create table public.notebook_capture_requests (
  user_id uuid not null references auth.users(id) on delete cascade,
  request_id uuid not null,
  note_id uuid references public.notebook_notes(id) on delete set null,
  primary key (user_id, request_id)
);
create index notebook_capture_requests_note_idx on public.notebook_capture_requests(note_id);
alter table public.notebook_capture_requests enable row level security;
revoke all on public.notebook_capture_requests from public, anon, authenticated;
grant select, insert on public.notebook_capture_requests to service_role;

create function public.capture_notebook_response(
  owner uuid, request uuid, destination uuid, source_course uuid,
  source_session uuid, source_message uuid, source_kind text, source_citations jsonb,
  fingerprint_arg text, note_title text, body_nodes jsonb, body_text text, legacy_nodes jsonb
) returns jsonb language plpgsql set search_path = '' as $$
declare
  target public.notebook_notes;
  source_id uuid;
  existing_id uuid;
  combined jsonb;
begin
  perform pg_advisory_xact_lock(hashtextextended(owner::text, 9171));
  select note_id into existing_id from public.notebook_capture_requests
    where user_id=owner and request_id=request;
  if found then
    return jsonb_build_object('state', case when existing_id is null then 'deleted' else 'saved' end, 'id', existing_id);
  end if;

  if not exists (
    select from public.messages m join public.sessions s on s.id=m.session_id
      join public.courses c on c.id=s.course_id
    where m.id=source_message and m.role='assistant' and s.id=source_session
      and c.id=source_course and c.user_id=owner
  ) then return jsonb_build_object('state','missing'); end if;

  if destination is null then
    -- The API gives each request a stable ID. Reopening the dialog for the same
    -- full response or selection finds the original captured note as well.
    select n.* into target from public.notebook_notes n join public.notebook_sources s on s.note_id=n.id
      where n.user_id=owner and s.fingerprint=fingerprint_arg and n.source_data->>'capture_fingerprint'=fingerprint_arg
      order by n.created_at limit 1;
    if not found then
      insert into public.notebook_notes(user_id,course_id,title,source_type,source_data)
        values(owner,source_course,note_title,
          case when source_kind='tutor' then 'manual' else source_kind end,jsonb_build_object('capture_fingerprint',fingerprint_arg))
        returning * into target;
    end if;
  else
    select * into target from public.notebook_notes where id=destination and user_id=owner for update;
    if not found then return jsonb_build_object('state','missing'); end if;
  end if;

  if not exists(select from public.notebook_sources where note_id=target.id and fingerprint=fingerprint_arg) then
    insert into public.notebook_sources(user_id,note_id,course_id,session_id,message_id,kind,citations,fingerprint)
      values(owner,target.id,source_course,source_session,source_message,source_kind,source_citations,fingerprint_arg)
      returning id into source_id;
    combined := coalesce(target.content_json->'content',
      case when target.content='' then '[]'::jsonb
        when legacy_nodes is not null and target.content=legacy_nodes->>'original' then legacy_nodes->'nodes'
        else (select jsonb_agg(jsonb_build_object('type','paragraph','content',
          case when line='' then '[]'::jsonb else jsonb_build_array(jsonb_build_object('type','text','text',line)) end) order by position)
          from regexp_split_to_table(target.content,E'\r?\n') with ordinality as lines(line,position))
      end) || body_nodes || jsonb_build_array(
        jsonb_build_object('type','sourceBlock','attrs',jsonb_build_object('sourceId',source_id)));
    if octet_length(combined::text)>1000000 or char_length(target.content)+char_length(body_text)+2>250000 then
      raise exception 'Note is too large' using errcode='22001';
    end if;
    update public.notebook_notes set content_json=jsonb_build_object('type','doc','content',combined),
      content=concat_ws(E'\n\n',nullif(content,''),body_text), version=version+1, updated_at=clock_timestamp()
      where id=target.id and user_id=owner;
  end if;
  insert into public.notebook_capture_requests(user_id,request_id,note_id) values(owner,request,target.id);
  return jsonb_build_object('state','saved','id',target.id);
end;
$$;
revoke all on function public.capture_notebook_response(uuid,uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text,jsonb,text,jsonb)
  from public, anon, authenticated;
grant execute on function public.capture_notebook_response(uuid,uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text,jsonb,text,jsonb)
  to service_role;
