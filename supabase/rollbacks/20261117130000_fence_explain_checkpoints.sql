-- Disable the Unit Pipeline before removing the RPC. Existing checkpoints remain readable.
begin;
drop function if exists public.append_explain_checkpoint(uuid,uuid,uuid,uuid,uuid,integer,text,uuid,uuid,integer,jsonb,jsonb,jsonb);
commit;
