from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

logger = logging.getLogger("sindio.auth")

JWT_SECRET = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "60"))

security = HTTPBearer(auto_error=False)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRY_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    if not JWT_SECRET:
        raise RuntimeError("JWT_SECRET environment variable is not set")
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["exp"]})


async def require_auth(request: Request) -> dict:
    credentials: Optional[HTTPAuthorizationCredentials] = await security(request)
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    try:
        payload = decode_access_token(credentials.credentials)
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


async def optional_auth(request: Request) -> Optional[dict]:
    credentials: Optional[HTTPAuthorizationCredentials] = await security(request)
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except JWTError:
        return None
