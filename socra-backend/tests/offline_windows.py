"""Run offline tests when a Windows sandbox blocks asyncio's loopback socket."""
from __future__ import annotations

import asyncio
import sys
import selectors
import time
import unittest


class OfflineSelector(selectors.SelectSelector):
    def select(self, timeout=None):
        if not self.get_map():
            time.sleep(min(timeout if timeout is not None else 0.01, 0.01))
            return []
        return super().select(timeout)


class OfflineLoop(asyncio.SelectorEventLoop):
    """Only for tests that use ASGI transports and subprocesses via threads."""

    def _make_self_pipe(self):
        self._csock = self._ssock = None

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        pass

    def _run_once(self):
        # Wake periodically to collect results from test threads.
        self.call_later(0.01, lambda: None)
        super()._run_once()

class OfflinePolicy(asyncio.DefaultEventLoopPolicy):
    def new_event_loop(self):
        return OfflineLoop(OfflineSelector())


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(OfflinePolicy())
    if len(sys.argv) == 1:
        sys.argv.extend(["discover", "-s", "tests"])
    unittest.main(module=None)
