"""
async_runner — bridges APScheduler background threads and synchronous LangGraph
nodes to the main FastAPI asyncio event loop.

Register at startup (inside lifespan):
    from app.services.async_runner import set_main_loop
    set_main_loop(asyncio.get_running_loop())

Call from any background thread or sync function:
    from app.services.async_runner import run_async
    result = run_async(some_coroutine(args))
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any, Coroutine

_log = logging.getLogger(__name__)
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Call once at application startup (inside lifespan) to register the main loop."""
    global _main_loop
    _main_loop = loop
    _log.info("[async_runner] Main event loop registered")


def run_async(coro: Coroutine, timeout: int = 90) -> Any:
    """Run *coro* from a background thread on the main event loop.

    Uses run_coroutine_threadsafe when the main loop is available — this shares
    the existing DB connection pool instead of creating throwaway connections.
    Falls back to asyncio.run() if the main loop is gone or not yet registered.
    Raises TimeoutError if the coroutine does not finish within *timeout* seconds.
    """
    loop = _main_loop
    if loop is not None and loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"Async task timed out after {timeout}s")
    _log.warning("[async_runner] Main loop not available — falling back to asyncio.run()")
    return asyncio.run(coro)
