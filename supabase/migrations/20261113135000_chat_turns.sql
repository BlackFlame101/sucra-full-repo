-- Existing messages and practice records have no chat request ID.
alter table public.messages add column chat_request_id uuid,
  add constraint messages_chat_request_unique unique (session_id, role, chat_request_id);
alter table public.exercises add column chat_request_id uuid,
  add constraint exercises_chat_request_unique unique (session_id, chat_request_id);
alter table public.exercise_attempts add column chat_request_id uuid,
  add constraint exercise_attempts_chat_request_unique unique (session_id, chat_request_id);

-- Only server routes publish answer metadata and idempotency keys.
revoke insert, update on public.messages from public, anon, authenticated;
grant select, insert, update on public.messages to service_role;

create table public.chat_turn_leases (
  session_id uuid primary key references public.sessions on delete cascade,
  token uuid not null,
  expires_at timestamptz not null
);
alter table public.chat_turn_leases enable row level security;
revoke all on public.chat_turn_leases from public, anon, authenticated;
grant all on public.chat_turn_leases to service_role;

create function public.acquire_chat_turn(inquiry uuid, owner_id uuid, lease uuid)
returns boolean language sql set search_path = '' as $$
  with acquired as (
    insert into public.chat_turn_leases(session_id, token, expires_at)
      select s.id, lease, now() + interval '5 minutes'
      from public.sessions s join public.courses c on c.id = s.course_id
      where s.id = inquiry and c.user_id = owner_id
    on conflict (session_id) do update set token = excluded.token, expires_at = excluded.expires_at
      where public.chat_turn_leases.expires_at <= now()
    returning true
  ) select exists (select from acquired);
$$;

create function public.release_chat_turn(inquiry uuid, lease uuid)
returns void language sql set search_path = '' as $$
  delete from public.chat_turn_leases where session_id = inquiry and token = lease;
$$;

revoke execute on function public.acquire_chat_turn(uuid,uuid,uuid), public.release_chat_turn(uuid,uuid) from public, anon, authenticated;
grant execute on function public.acquire_chat_turn(uuid,uuid,uuid), public.release_chat_turn(uuid,uuid) to service_role;
