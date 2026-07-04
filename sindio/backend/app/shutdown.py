"""Sindio — Graceful Shutdown Handler
=======================================
Ensures SIGTERM/SIGINT from Docker/K8s/Railway triggers clean shutdown:
  - Finish in-flight HTTP requests
  - Close DB connections
  - Flush logs
  - Stop background threads/tasks
"""
from __future__ import annotations

import logging
import signal
import sys
from typing import Callable, List

logger = logging.getLogger("sindio.shutdown")

_shutdown_handlers: List[Callable[[], None]] = []


def register_shutdown_handler(func: Callable[[], None]) -> None:
    """Register a function to be called on shutdown."""
    _shutdown_handlers.append(func)


def _handle_signal(signum: int, frame) -> None:
    """Handle SIGTERM / SIGINT."""
    sig_name = signal.Signals(signum).name
    logger.info("Received %s — starting graceful shutdown...", sig_name)

    for handler in _shutdown_handlers:
        try:
            handler()
        except Exception as exc:
            logger.warning("Shutdown handler failed: %s", exc)

    logger.info("Graceful shutdown complete. Exiting.")
    sys.exit(0)


def install_signal_handlers() -> None:
    """Install SIGTERM/SIGINT handlers. Call once at app startup."""
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    logger.info("Signal handlers installed (SIGTERM, SIGINT)")
