"""
Redis-backed task store for mock simulation jobs.

Keys (prefix ``sindio:sim:{task_id}:``):
  - ``state``       — PENDING | STARTED | SUCCESS | FAILURE
  - ``created_at``  — ISO-8601 timestamp
  - ``params``      — JSON dict with infrastructure_type, stress_factor, parameters
  - ``result``      — JSON dict with the full simulation result (GeoJSON, alerts, etc.)

All keys expire after *TTL* (default 3600 s = 1 hour).

If redis-py is not installed or Redis is unreachable, falls back to an
in-memory ``_FakeRedis`` (useful for local frontend development).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger("sindio.redis_store")

TTL = 3600
PREFIX = "sindio:sim:"


def _state_key(task_id: str) -> str:
    return f"{PREFIX}{task_id}:state"


def _created_key(task_id: str) -> str:
    return f"{PREFIX}{task_id}:created_at"


def _params_key(task_id: str) -> str:
    return f"{PREFIX}{task_id}:params"


def _result_key(task_id: str) -> str:
    return f"{PREFIX}{task_id}:result"

# ──────────────────────────────────────────────────────────────
# Redis / fallback client
# ──────────────────────────────────────────────────────────────

try:
    import redis as _redis_lib

    _pool: Optional[_redis_lib.ConnectionPool] = None
    _connected: bool = True

    def _get_redis() -> _redis_lib.Redis:
        global _pool, _connected
        if _pool is None:
            url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            _pool = _redis_lib.ConnectionPool.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
        if _connected:
            try:
                r = _redis_lib.Redis(connection_pool=_pool)
                r.ping()
                return r
            except _redis_lib.ConnectionError:
                _connected = False
                logger.warning(
                    "Redis unreachable — falling back to in-memory task store "
                    "(1-hour expiry only applies with real Redis)."
                )
        return _make_fake()

    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    logger.info("redis-py not installed — using in-memory task store")

    def _get_redis():
        return _make_fake()


_FAKE = None


def _make_fake():
    global _FAKE
    if _FAKE is None:
        _FAKE = _FakeRedis()
    return _FAKE


class _FakeRedis:
    def __init__(self):
        self._data: dict[str, str] = {}

    def get(self, key: str) -> Optional[str]:
        return self._data.get(key)

    def setex(self, key: str, ttl: int, value: str):
        self._data[key] = value

    def exists(self, key: str) -> bool:
        return key in self._data

    def delete(self, *keys: str):
        for k in keys:
            self._data.pop(k, None)

    def ping(self) -> bool:
        return True


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def create_task(task_id: str, params: dict) -> None:
    """Initialise a task with state PENDING."""
    r = _get_redis()
    now = params.get("created_at", "")
    infra = params.get("infrastructure_type", "")
    factor = params.get("stress_factor", "")
    extras = params.get("parameters")

    r.setex(_state_key(task_id), TTL, "PENDING")
    r.setex(_created_key(task_id), TTL, now)
    r.setex(
        _params_key(task_id),
        TTL,
        json.dumps({
            "infrastructure_type": infra,
            "stress_factor": factor,
            "parameters": extras,
        }),
    )


def set_started(task_id: str) -> None:
    """Transition task state to STARTED."""
    r = _get_redis()
    key = _state_key(task_id)
    if r.exists(key):
        r.setex(key, TTL, "STARTED")


def set_success(task_id: str, result: dict) -> None:
    """Transition task state to SUCCESS and store the result."""
    r = _get_redis()
    key = _state_key(task_id)
    if r.exists(key):
        r.setex(key, TTL, "SUCCESS")
        r.setex(_result_key(task_id), TTL, json.dumps(result))


def set_failure(task_id: str, reason: str = "") -> None:
    """Transition task state to FAILURE."""
    r = _get_redis()
    key = _state_key(task_id)
    if r.exists(key):
        r.setex(key, TTL, "FAILURE")
        if reason:
            r.setex(_result_key(task_id), TTL, json.dumps({"error": reason}))


def get_state(task_id: str) -> str:
    """Return PENDING | STARTED | SUCCESS | FAILURE or 'UNKNOWN'."""
    r = _get_redis()
    val = r.get(_state_key(task_id))
    return val if val else "UNKNOWN"


def get_result(task_id: str) -> Optional[dict]:
    """Return the stored result dict, or None if not SUCCESS yet."""
    r = _get_redis()
    raw = r.get(_result_key(task_id))
    if raw is None:
        return None
    return json.loads(raw)


def task_exists(task_id: str) -> bool:
    r = _get_redis()
    return bool(r.exists(_state_key(task_id)))
