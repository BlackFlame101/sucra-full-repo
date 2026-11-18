alter table public.courses add column notebook_private boolean not null default false;
create unique index courses_notebook_private_owner on public.courses(user_id) where notebook_private;

alter table public.notebook_notes add column review_due date;

create table public.notebook_threads (
  note_id uuid primary key references public.notebook_notes(id) on delete cascade,
  session_id uuid unique not null references public.sessions(id) on delete cascade
);
alter table public.notebook_threads enable row level security;
revoke all on public.notebook_threads from public, anon, authenticated;
grant select, insert on public.notebook_threads to service_role;

create table public.notebook_flashcards (
  note_id uuid primary key references public.notebook_notes(id) on delete cascade,
  note_version integer not null,
  cards jsonb not null check (jsonb_typeof(cards) = 'array' and jsonb_array_length(cards) between 1 and 12)
);
alter table public.notebook_flashcards enable row level security;
revoke all on public.notebook_flashcards from public, anon, authenticated;
grant select, insert, update on public.notebook_flashcards to service_role;

create function public.open_notebook_thread(owner uuid, note uuid)
returns jsonb language plpgsql set search_path = '' as $$
declare
  item public.notebook_notes;
  inquiry uuid;
  course uuid;
  response_language text;
begin
  perform pg_advisory_xact_lock(hashtextextended(owner::text, 9172));
  select * into item from public.notebook_notes where id=note and user_id=owner for update;
  if not found then return null; end if;
  select s.id,s.course_id,s.language into inquiry,course,response_language
    from public.notebook_threads t join public.sessions s on s.id=t.session_id
    join public.courses c on c.id=s.course_id and c.user_id=owner where t.note_id=note;
  if inquiry is null then
    insert into public.courses(user_id,name,notebook_private) values(owner,'Personal Notebook',true)
      on conflict (user_id) where notebook_private do nothing;
    select c.id into strict course from public.courses c where c.user_id=owner and c.notebook_private;
    select s.language into response_language from public.notebook_sources ns
      join public.sessions s on s.id=ns.session_id join public.courses c on c.id=s.course_id and c.user_id=owner
      where ns.note_id=note and ns.user_id=owner order by ns.created_at desc limit 1;
    response_language := coalesce(response_language,'en');
    insert into public.sessions(course_id,title,language) values(course,left('Notebook: ' || item.title,240),response_language)
      returning id into inquiry;
    insert into public.notebook_threads values(note,inquiry);
  end if;
  return jsonb_build_object('sessionId',inquiry,'courseId',course,'language',response_language);
end;
$$;
revoke all on function public.open_notebook_thread(uuid,uuid) from public, anon, authenticated;
grant execute on function public.open_notebook_thread(uuid,uuid) to service_role;

-- Notebook questions are verified against note text and have no invented PDF citations.
alter table public.exercises add column notebook_grounded boolean not null default false;
alter table public.exercises drop constraint exercises_citations_check,
  add constraint exercises_citations_check check (jsonb_typeof(citations)='array' and
    (jsonb_array_length(citations) between 1 and 3 or (notebook_grounded and jsonb_array_length(citations)=0)));
