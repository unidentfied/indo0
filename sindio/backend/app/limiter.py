import os
from slowapi import Limiter
from slowapi.util import get_remote_address

_env = os.getenv("ENV", "development")
_default_limits = [] if _env == "test" else ["120/minute"]
_kwargs = {"key_func": get_remote_address, "default_limits": _default_limits}
if _env == "test":
    _kwargs["enabled"] = False
_redis_url = os.getenv("REDIS_URL")
if _redis_url:
    _kwargs["storage_uri"] = _redis_url
limiter = Limiter(**_kwargs)
