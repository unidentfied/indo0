"""Sindio — Circuit Breaker Pattern
=====================================
Prevents cascading failures when external APIs are down.

Usage:
    from app.circuit_breaker import CircuitBreaker, circuit_breaker

    cb = CircuitBreaker("opensky", failure_threshold=5, recovery_timeout=60)
    result = cb.call(my_api_function, arg1, arg2)
"""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("sindio.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker for external API calls.

    States:
      CLOSED → OPEN: after `failure_threshold` consecutive failures
      OPEN → HALF_OPEN: after `recovery_timeout` seconds
      HALF_OPEN → CLOSED: if test call succeeds
      HALF_OPEN → OPEN: if test call fails
    """

    _registry: Dict[str, "CircuitBreaker"] = {}
    _lock = threading.RLock()

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0

    @classmethod
    def get(cls, name: str, **kwargs) -> "CircuitBreaker":
        with cls._lock:
            if name not in cls._registry:
                cls._registry[name] = cls(name, **kwargs)
            return cls._registry[name]

    def call(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with circuit breaker protection."""
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to(CircuitState.HALF_OPEN)
            else:
                raise CircuitBreakerOpen(
                    f"Circuit '{self.name}' is OPEN. Last failure: "
                    f"{self._seconds_since_last_failure():.0f}s ago"
                )

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.half_open_max_calls:
                raise CircuitBreakerOpen(
                    f"Circuit '{self.name}' HALF_OPEN limit reached"
                )
            self.half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self):
        self.failure_count = 0
        if self.state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.CLOSED)
            logger.info("Circuit '%s' recovered — CLOSED", self.name)

    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.monotonic()

        if self.state == CircuitState.HALF_OPEN:
            self._transition_to(CircuitState.OPEN)
            logger.warning(
                "Circuit '%s' re-opened after half-open failure (count=%d)",
                self.name, self.failure_count,
            )
        elif self.failure_count >= self.failure_threshold:
            self._transition_to(CircuitState.OPEN)
            logger.error(
                "Circuit '%s' OPENED after %d failures",
                self.name, self.failure_count,
            )

    def _should_attempt_reset(self) -> bool:
        if self.last_failure_time is None:
            return True
        return (time.monotonic() - self.last_failure_time) >= self.recovery_timeout

    def _transition_to(self, new_state: CircuitState):
        old_state = self.state
        self.state = new_state
        if new_state == CircuitState.HALF_OPEN:
            self.half_open_calls = 0
        logger.info("Circuit '%s': %s → %s", self.name, old_state.value, new_state.value)

    def _seconds_since_last_failure(self) -> float:
        if self.last_failure_time is None:
            return float("inf")
        return time.monotonic() - self.last_failure_time

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "last_failure_seconds_ago": round(self._seconds_since_last_failure(), 1),
            "recovery_timeout": self.recovery_timeout,
        }


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is OPEN."""
    pass


# Pre-configured circuit breakers for external APIs

circuit_breaker = CircuitBreaker.get

# Usage in fetchers:
# cb = circuit_breaker("opensky", failure_threshold=3, recovery_timeout=120)
# data = cb.call(self._fetch_live, station)
