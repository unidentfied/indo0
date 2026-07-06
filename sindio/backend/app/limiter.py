import os
from slowapi import Limiter
from slowapi.util import get_remote_address

_redis_url = os.getenv("REDIS_URL")
_kwargs = {"key_func": get_remote_address, "default_limits": ["120/minute"]}
if _redis_url:
    _kwargs["storage_uri"] = _redis_url
limiter = Limiter(**_kwargs)
