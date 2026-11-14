"""Shared checks at the FastAPI service boundary."""
from __future__ import annotations

import asyncio
import logging

from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

from db.supabase_client import get_supabase

logger = logging.getLogger(__name__)


class RateLimit:
    def __init__(self, maximum: int, window_seconds: int = 60):
        self.maximum = maximum
        self.window_seconds = window_seconds
        self._users: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = Lock()

    def allow(self, user_id: str) -> bool:
        now = monotonic()
        with self._lock:
            while self._users and next(iter(self._users.values()))[-1] <= now - self.window_seconds:
                self._users.popitem(last=False)
            if user_id not in self._users and len(self._users) >= 10_000:
                return False
            timestamps = self._users.setdefault(user_id, deque())
            while timestamps and timestamps[0] <= now - self.window_seconds:
                timestamps.popleft()
            if len(timestamps) >= self.maximum:
                return False
            timestamps.append(now)
            self._users.move_to_end(user_id)
            return True


async def consume_study_quota(owner: str, operation: str) -> bool | None:
    try:
        result = await asyncio.to_thread(lambda: get_supabase().rpc(
            "consume_study_quota", {"owner": owner, "operation_name": operation},
        ).retry(False).execute())
        return result.data is True
    except Exception as exc:
        logger.warning("study_quota_unavailable operation=%s error_type=%s", operation, type(exc).__name__)
        return None
