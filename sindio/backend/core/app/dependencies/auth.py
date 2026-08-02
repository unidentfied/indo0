import os
from datetime import datetime, timezone
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

bearer_scheme = HTTPBearer()


class User(BaseModel):
    sub: str
    email: str | None = None
    roles: list[str] = []
    is_paid: bool = False
    is_trial: bool = False
    trial_expires_at: datetime | None = None


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> User:
    token = credentials.credentials
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="JWT secret not configured — authentication unavailable",
        )
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        return User(**payload)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

# Helper to determine if the user is allowed (paid or active trial)
def is_active_user(current_user: User = Depends(get_current_user)) -> User:
    # If user is paid, allow
    if getattr(current_user, "is_paid", False):
        return current_user
    # If trial active
    if getattr(current_user, "is_trial", False) and current_user.trial_expires_at:
        if current_user.trial_expires_at > datetime.now(timezone.utc):
            return current_user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Subscription required or trial expired",
    )
