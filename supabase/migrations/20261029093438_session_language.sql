alter table public.sessions
  add column if not exists language text not null default 'fr'
  check (language in ('fr', 'en'));
