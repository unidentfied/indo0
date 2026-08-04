from __future__ import annotations

import structlog
import os
import hmac
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

# Email utilities

# Local helpers (will be defined later)
from .email_utils import generate_verification_token, send_verification_email, verify_token


logger = structlog.get_logger("sindio.auth")

# Environment variables
JWT_SECRET = os.getenv("JWT_SECRET", "sindio-dev-secret-change-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
# Prefer explicit minutes, otherwise compute from hours (default 1 hour)
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", str(int(os.getenv("JWT_EXPIRY_HOURS", "1")) * 60)))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))
AUTH_USERNAME = os.getenv("AUTH_USERNAME", "admin")
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD", "")

from sqlalchemy.orm import Session
from .database import get_engine
from .models.user import User
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    """FastAPI dependency providing a DB session."""
    engine = get_engine()
    SessionLocal = Session(bind=engine)
    try:
        yield SessionLocal
    finally:
        SessionLocal.close()

security = HTTPBearer(auto_error=False)

auth_router = APIRouter()

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    if not JWT_SECRET:
        raise HTTPException(status_code=401, detail="JWT_SECRET not configured — authentication unavailable")
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=JWT_EXPIRY_MINUTES))
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    if not JWT_SECRET:
        raise HTTPException(status_code=401, detail="JWT_SECRET not configured — authentication unavailable")
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"require": ["exp"]})


async def require_auth(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    try:
        payload = decode_access_token(credentials.credentials)
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


async def optional_auth(request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Optional[dict]:
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except (JWTError, HTTPException):
        return None


# --- New Auth Endpoints ---

# User signup
class UserCreate(BaseModel):
    email: str
    password: str

@auth_router.post("/signup", response_model=TokenResponse)
async def signup(user: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    # Hash password
    pwd_hash = pwd_context.hash(user.password)
    # Set trial fields
    trial_expires = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)
    new_user = User(email=user.email, password_hash=pwd_hash, is_verified=False, is_trial=True, trial_expires_at=trial_expires)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    # Generate verification token
    try:
        token = generate_verification_token(user.email)
        background_tasks.add_task(send_verification_email, user.email, token)
    except Exception as exc:
        logger.warning("verification_email_skipped", email=user.email, error=str(exc))
    # Issue JWT token (user can log in after verification)
    access_token = create_access_token(data={"sub": new_user.email, "is_paid": new_user.is_paid, "is_trial": new_user.is_trial, "trial_expires_at": new_user.trial_expires_at.isoformat() if new_user.trial_expires_at else None})
    return TokenResponse(access_token=access_token, expires_in=JWT_EXPIRY_MINUTES * 60)

# User login endpoint (email & password)
@auth_router.post("/login", response_model=TokenResponse)
async def login(credentials: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not pwd_context.verify(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    # Issue JWT with subscription/trial info
    token_data = {"sub": user.email, "is_paid": user.is_paid, "is_trial": user.is_trial, "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None}
    access_token = create_access_token(data=token_data)
    return TokenResponse(access_token=access_token, expires_in=JWT_EXPIRY_MINUTES * 60)

# Email verification endpoint (kept unchanged)
@auth_router.get("/verify-email/{token}")
async def verify_email(token: str, db: Session = Depends(get_db)):
    try:
        email = verify_token(token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_verified:
        return {"detail": "Email already verified"}
    user.is_verified = True
    db.commit()
    return {"detail": "Email verified successfully"}


