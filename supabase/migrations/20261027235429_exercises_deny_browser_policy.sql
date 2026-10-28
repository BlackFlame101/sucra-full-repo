-- Make the browser denial explicit in RLS in addition to revoking table grants.
drop policy if exists exercises_browser_denied on public.exercises;
create policy exercises_browser_denied
  on public.exercises
  for all
  to anon, authenticated
  using (false)
  with check (false);
