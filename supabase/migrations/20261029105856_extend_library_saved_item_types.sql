alter table public.library_items
  drop constraint if exists library_items_item_type_check;

alter table public.library_items
  add constraint library_items_item_type_check
  check (item_type in ('explanation', 'exercise', 'inquiry', 'exam'));
