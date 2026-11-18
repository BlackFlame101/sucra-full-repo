begin;

create function public.append_explain_checkpoint(
  p_inquiry uuid, p_course uuid, p_owner uuid, p_lease uuid,
  p_document uuid, p_generation integer, p_source_hash text,
  p_message uuid, p_request uuid, p_expected_revision integer,
  p_version jsonb, p_call jsonb, p_final jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
  source_row public.documents%rowtype;
  lease_row public.chat_turn_leases%rowtype;
  checkpoint jsonb;
  identity_fields jsonb;
  answer public.messages%rowtype;
begin
  if p_lease is null or p_generation is null or p_source_hash is null
     or num_nonnulls(p_version, p_call, p_final) <> 1
     or (p_version is not null and (
       jsonb_typeof(p_version) <> 'object'
       or (p_version->>'request_id') is distinct from p_request::text
       or (p_version->>'document_id') is distinct from p_document::text
       or (p_version->>'generation') is distinct from p_generation::text
       or (p_version->>'source_hash') is distinct from p_source_hash))
     or (p_call is not null and jsonb_typeof(p_call) <> 'object')
     or (p_final is not null and (
       (p_final->'metadata'->>'request_id') is distinct from p_request::text
       or (p_final->'metadata'->'explanation'->>'schema_version') is distinct from '2'
       or not coalesce((p_final->'metadata'->'explanation'->'course_progress') @>
         jsonb_build_object('document_id', p_document, 'source_hash', p_source_hash, 'index_generation', p_generation), false)
       or jsonb_typeof(p_final->'content') is distinct from 'string')) then
    return 'false'::jsonb;
  end if;

  -- Lock order: course, inquiry, document, lease, prompt. Hold all locks until commit.
  -- Existing reindexers update the document row. Takeover and release modify the lease row.
  perform 1 from public.courses where id = p_course and user_id = p_owner for share;
  if not found then return 'false'::jsonb; end if;
  perform 1 from public.sessions where id = p_inquiry and course_id = p_course for share;
  if not found then return 'false'::jsonb; end if;
  select * into source_row from public.documents where id = p_document and course_id = p_course for share;
  if not found or source_row.index_generation is distinct from p_generation
     or source_row.content_hash is distinct from p_source_hash
     or source_row.index_status is distinct from 'ready' or source_row.index_stage is not null then
    return 'false'::jsonb;
  end if;
  select * into lease_row from public.chat_turn_leases where session_id = p_inquiry for update;
  if not found or lease_row.token is distinct from p_lease or lease_row.expires_at <= clock_timestamp() then
    return 'false'::jsonb;
  end if;
  select metadata->'explain_unit_checkpoint' into checkpoint from public.messages
    where id = p_message and session_id = p_inquiry and role = 'user' and chat_request_id = p_request
    for update;
  if not found or (checkpoint->'revision') is distinct from to_jsonb(p_expected_revision) then
    return 'false'::jsonb;
  end if;

  identity_fields := jsonb_build_object('request_id', p_request, 'document_id', p_document,
                                        'source_hash', p_source_hash, 'generation', p_generation);
  if checkpoint is null then
    checkpoint := identity_fields || '{"versions":[],"calls":[]}'::jsonb;
  elsif not checkpoint @> identity_fields
        or jsonb_typeof(checkpoint->'versions') is distinct from 'array'
        or jsonb_typeof(checkpoint->'calls') is distinct from 'array' then
    return 'false'::jsonb;
  end if;
  -- Recheck wall-clock expiry after any waits on the prompt row.
  if lease_row.expires_at <= clock_timestamp() then return 'false'::jsonb; end if;
  if p_final is not null then
    insert into public.messages(session_id, role, chat_request_id, content, metadata)
    values (p_inquiry, 'assistant', p_request, p_final->>'content', p_final->'metadata')
    on conflict (session_id, role, chat_request_id) do nothing
    returning * into answer;
    if not found then
      select * into answer from public.messages
      where session_id = p_inquiry and role = 'assistant' and chat_request_id = p_request;
    end if;
    return to_jsonb(answer);
  end if;
  if p_version is not null then
    checkpoint := jsonb_set(checkpoint, '{versions}', (checkpoint->'versions') || jsonb_build_array(p_version));
  else
    checkpoint := jsonb_set(checkpoint, '{calls}', (checkpoint->'calls') || jsonb_build_array(p_call));
  end if;
  checkpoint := jsonb_set(checkpoint, '{revision}', to_jsonb(coalesce(p_expected_revision, 0) + 1));

  update public.messages
     set metadata = jsonb_set(coalesce(metadata, '{}'::jsonb), '{explain_unit_checkpoint}', checkpoint)
   where id = p_message;
  return to_jsonb(found);
end;
$$;

revoke all on function public.append_explain_checkpoint(uuid,uuid,uuid,uuid,uuid,integer,text,uuid,uuid,integer,jsonb,jsonb,jsonb)
  from public, anon, authenticated;
grant execute on function public.append_explain_checkpoint(uuid,uuid,uuid,uuid,uuid,integer,text,uuid,uuid,integer,jsonb,jsonb,jsonb)
  to service_role;

commit;
