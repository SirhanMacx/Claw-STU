"""In-memory per-process rate limiter.

Modeled on Claw-ED's ``clawed.api.deps._RateLimiter`` for cross-repo
consistency. No external dependencies: timestamps are stored in a
plain dict, pruned every 100th request to prevent memory leaks.

In-memory per-process limiter. For multi-process or distributed
deployments, replace with a shared backend (Redis, etc.).

Usage::

    from clawstu.api.rate_limit import limiter

    @router.post("/sessions")
    @limiter.limit("10/minute")
    async def onboard(request: Request, ...):
        ...

The decorator extracts the client IP from the ``Request`` object.
If the handler signature omits ``request: Request``, a warning is
logged and the rate limit is **not** silently bypassed.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Callable
from functools import wraps
from typing import Any

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

_rate_store: dict[str, list[float]] = defaultdict(list)
_rate_request_count: int = 0


def _cleanup_rate_store(window: int) -> None:
    """Remove stale entries to prevent unbounded memory growth.

    Called every 100th request.  Deletes timestamps older than
    *window* seconds and drops keys that become empty.
    """
    now = time.time()
    empty_keys: list[str] = []
    for key in list(_rate_store.keys()):
        _rate_store[key] = [t for t in _rate_store[key] if t > now - window]
        if not _rate_store[key]:
            empty_keys.append(key)
    for key in empty_keys:
        del _rate_store[key]


class _RateLimiter:
    """Simple in-memory rate limiter.  No external dependencies."""

    # HEARTBEAT: single-responsibility, no natural seam
    def limit(self, rate_string: str) -> Callable[..., Any]:
        """Decorator: enforce a rate limit like ``'30/minute'``."""
        count_str, _, period = rate_string.partition("/")
        max_calls = int(count_str)
        window = {"second": 1, "minute": 60, "hour": 3600}.get(period, 60)

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                global _rate_request_count

                # Extract Request from kwargs (any name) or args.
                # FastAPI injects dependencies as kwargs; the param may
                # be named ``request``, ``http_request``, etc.
                request = None
                for val in kwargs.values():
                    if isinstance(val, Request):
                        request = val
                        break
                if request is None:
                    for arg in args:
                        if isinstance(arg, Request):
                            request = arg
                            break

                if request is not None:
                    client = (
                        request.client.host if request.client else "unknown"
                    )
                    key = f"{client}:{func.__name__}"
                    now = time.time()

                    _rate_request_count += 1
                    if _rate_request_count % 100 == 0:
                        _cleanup_rate_store(window)

                    _rate_store[key] = [
                        t for t in _rate_store[key] if t > now - window
                    ]

                    if len(_rate_store[key]) >= max_calls:
                        raise HTTPException(
                            status_code=429,
                            detail=f"Rate limit exceeded ({rate_string})",
                        )
                    _rate_store[key].append(now)
                else:
                    logger.warning(
                        "Rate limiter on %s has no Request in signature; "
                        "limit %s is NOT being enforced.  Add "
                        "`request: Request` to the handler.",
                        func.__name__,
                        rate_string,
                    )

                return await func(*args, **kwargs)

            return wrapper

        return decorator


limiter = _RateLimiter()


def reset_rate_state() -> None:
    """Clear the in-memory rate store.  For tests only."""
    global _rate_request_count
    _rate_store.clear()
    _rate_request_count = 0
