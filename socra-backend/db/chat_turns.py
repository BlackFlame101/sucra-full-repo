"""Serialize turns across sockets so profile updates follow answer order."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


@asynccontextmanager
async def session_turn(session_id: str, user_id: str):
    lease = str(uuid4())
    params = {"inquiry": session_id, "lease": lease}
    try:
        result = await asyncio.to_thread(
            lambda: get_supabase().rpc("acquire_chat_turn", {**params, "owner_id": user_id}).retry(False).execute()
        )
        acquired = result.data is True
    except Exception as exc:
        logger.warning("chat_lock_failed error_type=%s", type(exc).__name__)
        acquired = False
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await asyncio.to_thread(lambda: get_supabase().rpc("release_chat_turn", params).execute())
            except Exception as exc:
                logger.warning("chat_unlock_failed error_type=%s", type(exc).__name__)
