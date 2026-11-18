-- Turn state is read after authentication and while the inquiry lease is held.
create function public.load_study_turn(inquiry uuid, owner uuid, request uuid)
returns jsonb language sql stable set search_path = '' as $$
  select jsonb_build_object(
    'language',s.language,
    'profile',(select to_jsonb(p) from public.student_profiles p where p.session_id = s.id and p.user_id = owner limit 1),
    'diagnostic',(select to_jsonb(d) from public.diagnostics d where d.session_id = s.id order by d.created_at desc limit 1),
    'recent',coalesce((select jsonb_agg(to_jsonb(m) order by m.created_at,m.id)
      from (select id,role,content,metadata,created_at from public.messages
            where session_id = s.id order by created_at desc,id desc limit 32) m),'[]'::jsonb),
    'is_exam',exists(select from public.exams e where e.session_id=s.id and e.user_id=owner),
    'has_assistant',exists(select from public.messages where session_id = s.id and role = 'assistant'),
    'request_messages',coalesce((select jsonb_agg(jsonb_build_object('id',m.id,'role',m.role,'content',m.content,'metadata',m.metadata))
      from public.messages m where m.session_id = s.id and m.chat_request_id = request),'[]'::jsonb)
  )
  from public.sessions s join public.courses c on c.id = s.course_id
  where s.id = inquiry and c.user_id = owner;
$$;
create index study_messages_recent on public.messages(session_id,created_at desc,id desc);

create function public.current_course_sections(course uuid)
returns table(document_id uuid,document_version text,level text,title text,summary text,page_start integer,page_end integer)
language sql stable set search_path = '' as $$
  select s.document_id,s.document_version,s.level,s.title,s.summary,s.page_start,s.page_end
  from public.document_summaries s join public.documents d on d.id=s.document_id and d.course_id=s.course_id
  where d.course_id=course and d.index_status='ready' and d.content_hash=s.document_version and s.level='section'
  order by s.document_id,s.page_start limit 200;
$$;

-- Optional lexical candidates. The expression uses the 'simple' dictionary to retain
-- French/English words and programming identifiers without language-specific stemming.
create index embeddings_search_terms on public.embeddings using gin(to_tsvector('pg_catalog.simple'::regconfig, content));

create function public.match_course_terms(course uuid, search_text text, match_count integer default 12)
returns table(id uuid,content text,document_id uuid,page_number integer,chunk_index integer,filename text,similarity double precision)
language sql stable set search_path = '' as $$
  with q as (select websearch_to_tsquery('pg_catalog.simple'::regconfig,left(search_text,500)) as terms)
  select e.id,e.content,e.document_id,e.page_number,e.chunk_index,d.filename,0::double precision
  from public.embeddings e join public.documents d on d.id=e.document_id cross join q
  where d.course_id=course and d.index_status='ready'
    and to_tsvector('pg_catalog.simple'::regconfig,e.content) @@ q.terms
  order by ts_rank_cd(to_tsvector('pg_catalog.simple'::regconfig,e.content),q.terms) desc,e.id
  limit least(greatest(match_count,1),60);
$$;

revoke execute on function public.load_study_turn(uuid,uuid,uuid), public.current_course_sections(uuid),
  public.match_course_terms(uuid,text,integer) from public, anon, authenticated;
grant execute on function public.load_study_turn(uuid,uuid,uuid), public.current_course_sections(uuid),
  public.match_course_terms(uuid,text,integer) to service_role;
