-- Local development only. Run against a fresh Supabase instance before migrations.
-- Auth, Storage, and standard Supabase roles are supplied by the local stack.
create extension if not exists vector with schema extensions;

create table public.courses (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users on delete cascade,
  name text not null,
  description text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.sessions (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses on delete cascade,
  title text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create table public.documents (
  id uuid primary key default gen_random_uuid(),
  course_id uuid not null references public.courses on delete cascade,
  filename text not null,
  storage_path text not null,
  page_count integer,
  file_size integer,
  created_at timestamptz not null default now()
);
create table public.embeddings (
  id uuid primary key default gen_random_uuid(),
  document_id uuid not null references public.documents on delete cascade,
  content text not null,
  embedding extensions.vector(768),
  metadata jsonb default '{}',
  page_number integer,
  chunk_index integer,
  created_at timestamptz not null default now()
);
create table public.messages (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  metadata jsonb default '{}',
  created_at timestamptz not null default now()
);
create table public.diagnostics (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions on delete cascade,
  topic text,
  initial_level text check (initial_level in ('beginner','intermediate','advanced')),
  identified_gaps jsonb not null default '[]',
  prerequisite_concepts jsonb not null default '[]',
  created_at timestamptz not null default now()
);
create table public.key_terms (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.sessions on delete cascade,
  term text not null,
  created_at timestamptz not null default now()
);
create table public.student_profiles (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null unique references public.sessions on delete cascade,
  user_id uuid not null references auth.users on delete cascade,
  mastered_concepts jsonb not null default '[]',
  fragile_concepts jsonb not null default '[]',
  misconception_history jsonb not null default '[]',
  bloom_progression jsonb not null default '[]',
  total_exchanges integer not null default 0,
  updated_at timestamptz not null default now()
);

create index courses_owner_idx on public.courses(user_id);
create index sessions_course_idx on public.sessions(course_id);
create index documents_course_idx on public.documents(course_id);
create index embeddings_document_idx on public.embeddings(document_id);
create index embeddings_vector_idx on public.embeddings using hnsw (embedding extensions.vector_cosine_ops);
create index messages_session_idx on public.messages(session_id);
create index diagnostics_session_idx on public.diagnostics(session_id);
create index key_terms_session_idx on public.key_terms(session_id);

alter table public.courses enable row level security;
alter table public.sessions enable row level security;
alter table public.documents enable row level security;
alter table public.embeddings enable row level security;
alter table public.messages enable row level security;
alter table public.diagnostics enable row level security;
alter table public.key_terms enable row level security;
alter table public.student_profiles enable row level security;

revoke all on public.courses,public.sessions,public.documents,public.embeddings,public.messages,
  public.diagnostics,public.key_terms,public.student_profiles from public,anon,authenticated;
grant all on public.courses,public.sessions,public.documents,public.embeddings,public.messages,
  public.diagnostics,public.key_terms,public.student_profiles to service_role;
grant select,insert,update,delete on public.courses,public.sessions to authenticated;
grant select,delete on public.messages to authenticated;
grant select on public.documents,public.embeddings,public.diagnostics,public.key_terms,public.student_profiles to authenticated;

create policy courses_owner on public.courses to authenticated
  using (user_id=(select auth.uid())) with check (user_id=(select auth.uid()));
create policy sessions_owner on public.sessions to authenticated
  using (exists(select from public.courses c where c.id=course_id and c.user_id=(select auth.uid())))
  with check (exists(select from public.courses c where c.id=course_id and c.user_id=(select auth.uid())));
create policy documents_owner on public.documents for select to authenticated
  using (exists(select from public.courses c where c.id=course_id and c.user_id=(select auth.uid())));
create policy embeddings_owner on public.embeddings for select to authenticated
  using (exists(select from public.documents d where d.id=document_id));
create policy messages_owner on public.messages to authenticated
  using (exists(select from public.sessions s where s.id=session_id));
create policy diagnostics_owner on public.diagnostics for select to authenticated
  using (exists(select from public.sessions s where s.id=session_id));
create policy key_terms_owner on public.key_terms for select to authenticated
  using (exists(select from public.sessions s where s.id=session_id));
create policy profiles_owner on public.student_profiles for select to authenticated
  using (user_id=(select auth.uid()));

insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
  values ('documents','documents',false,52428800,array['application/pdf']);
create policy documents_bucket_owner on storage.objects for select to authenticated
  using (bucket_id='documents' and (storage.foldername(name))[1]=(select auth.uid())::text);

create function public.set_updated_at() returns trigger language plpgsql set search_path = '' as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
create trigger courses_updated_at before update on public.courses for each row execute function public.set_updated_at();
create trigger sessions_updated_at before update on public.sessions for each row execute function public.set_updated_at();
create trigger profiles_updated_at before update on public.student_profiles for each row execute function public.set_updated_at();
