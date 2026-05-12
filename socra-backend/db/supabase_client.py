"""Supabase client singleton.

The Python backend uses the *service role key* so it can bypass RLS when
writing on behalf of the authenticated user. All writes that originate from a
specific user must explicitly carry that ``user_id`` to keep ownership intact.
"""
from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from config import get_settings


@lru_cache(maxsize=1)
def get_supabase() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
