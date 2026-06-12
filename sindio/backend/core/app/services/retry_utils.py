"""
Retry decorator for external data fetches (PostGIS, Qdrant, Kafka, HTTP).

Retries 3x with exponential back-off (1 s, 2 s, 4 s). On final failure the
decorator can either raise or invoke a *fallback* callable. Logs every
attempt and always emits a warning on exhaustion — never a crash.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable, Optional, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

logger = logging.getLogger("sindio.retry")

RETRIABLE = (
    ConnectionError,
    ConnectionRefusedError,
    ConnectionResetError,
    TimeoutError,
    OSError,
    IOError,
)

try:
    import psycopg2

    RETRIABLE += (psycopg2.OperationalError, psycopg2.InterfaceError)
except ImportError:
    pass

try:
    import redis as _redis_lib

    RETRIABLE += (_redis_lib.ConnectionError,)
except ImportError:
    pass


def retry_external(
    retries: int = 3,
    backoff_base: float = 1.0,
    fallback: Optional[Callable[..., Any]] = None,
    label: str = "",
) -> Callable[[F], F]:
    """
    Wrap a function so it is retried up to *retries* times with
    exponential back-off (``backoff_base * 2**attempt``).

    If *fallback* is provided it is called with the same ``*args, **kwargs``
    when all retries are exhausted; its return value stands in for the
    original.  Otherwise the original exception is re-raised (logged as
    warning first).

    Example::

        @retry_external(retries=3, backoff_base=1.0, label="qdrant_search")
        def search_qdrant(embedding, limit=20):
            ...
    """
    def _decorator(func: F) -> F:
        @functools.wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            description = label or f"{func.__module__}.{func.__qualname__}"
            attempt = 0
            last_exc: Optional[Exception] = None

            while attempt < retries:
                try:
                    return func(*args, **kwargs)
                except RETRIABLE as exc:
                    attempt += 1
                    last_exc = exc
                    delay = backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "%s — attempt %d/%d failed (%s). Retrying in %.1f s…",
                        description, attempt, retries, exc, delay,
                    )
                    time.sleep(delay)
                except Exception as exc:
                    attempt += 1
                    last_exc = exc
                    delay = backoff_base * (2 ** (attempt - 1))
                    logger.warning(
                        "%s — attempt %d/%d failed with unclassified error (%s). Retrying in %.1f s…",
                        description, attempt, retries, exc, delay,
                    )
                    time.sleep(delay)

            logger.warning(
                "%s — all %d retries exhausted (last: %s).",
                description, retries, last_exc,
            )

            if fallback is not None:
                logger.info("%s — invoking fallback.", description)
                return fallback(*args, **kwargs)

            if last_exc:
                raise last_exc
            raise RuntimeError(f"{description} — retries exhausted with no recorded exception")

        return _wrapper  # type: ignore[return-value]
    return _decorator
