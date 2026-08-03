from functools import wraps

import structlog

logger = structlog.get_logger("sindio.retry")


def retry_if_enabled(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.warning("retry_fallback", func=func.__name__)
            raise

    return wrapper
