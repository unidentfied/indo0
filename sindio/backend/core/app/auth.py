from __future__ import annotations

import structlog
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel

# Email utilities

# Local helpers (will be defined later)
from .email_utils import generate_verification_token, send_verification_email, verify_token, test_smtp_connection


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


# --- Auth Endpoints ---

class UserCreate(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class UserLogin(BaseModel):
    email: str
    password: str

class ResendVerificationRequest(BaseModel):
    email: str


def _queue_verification_email(user: User, background_tasks: BackgroundTasks) -> tuple[bool, str]:
    try:
        token = generate_verification_token(user.email)
        background_tasks.add_task(send_verification_email, user.email, token)
        logger.info("verification_email_queued", email=user.email)
        return True, ""
    except Exception as exc:
        logger.error("verification_email_failed", email=user.email, error=str(exc))
        return False, "Email service is temporarily unavailable. Please try again or contact support."


def _make_user_token(user: User) -> dict[str, Any]:
    return {
        "sub": user.email,
        "name": user.name,
        "is_paid": user.is_paid,
        "is_trial": user.is_trial,
        "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
    }


@auth_router.post("/signup")
async def signup(user: UserCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == user.email).first()
    if existing:
        if not existing.is_verified:
            email_ok, email_error = _queue_verification_email(existing, background_tasks)
            return {
                "detail": "Account already exists but is not verified. A new verification email has been sent.",
                "verified": False,
                "verification_email_sent": email_ok,
                "email_error": email_error,
            }
        raise HTTPException(status_code=409, detail="An account with this email already exists")

    pwd_hash = pwd_context.hash(user.password)
    trial_expires = datetime.now(timezone.utc) + timedelta(days=TRIAL_DAYS)

    new_user = User(
        name=user.name,
        email=user.email,
        password_hash=pwd_hash,
        is_verified=False,
        is_trial=True,
        trial_expires_at=trial_expires,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    email_ok, email_error = _queue_verification_email(new_user, background_tasks)

    return {
        "detail": "Account created. Please check your email for the verification link.",
        "verified": False,
        "verification_email_sent": email_ok,
        "email_error": email_error,
        "trial_days": TRIAL_DAYS,
        "trial_expires_at": trial_expires.isoformat(),
    }


@auth_router.post("/resend-verification")
async def resend_verification(body: ResendVerificationRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="No account found with this email address")
    if user.is_verified:
        return {"detail": "Email is already verified. You can sign in.", "verified": True, "verification_email_sent": False}

    email_ok, email_error = _queue_verification_email(user, background_tasks)
    if not email_ok:
        raise HTTPException(status_code=500, detail=email_error or "Failed to send verification email. Please try again later.")

    return {"detail": "Verification email resent. Please check your inbox.", "verified": False, "verification_email_sent": True}

# User login endpoint (email & password)
@auth_router.post("/login")
async def login(credentials: UserLogin, db: Session = Depends(get_db)):
    if not credentials.email or not credentials.password:
        raise HTTPException(status_code=422, detail="Email and password are required")
    user = db.query(User).filter(User.email == credentials.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not pwd_context.verify(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before signing in. Check your inbox for the verification link.")
    token_data = _make_user_token(user)
    access_token = create_access_token(data=token_data)
    return {"access_token": access_token, "token_type": "bearer", "expires_in": JWT_EXPIRY_MINUTES * 60}

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

@auth_router.delete("/account")
async def delete_account(payload: dict[str, Any] = Depends(require_auth), db: Session = Depends(get_db)):
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    logger.info("account_deleted", email=email)
    return {"detail": "Account deleted successfully"}


@auth_router.get("/debug/email-status")
async def debug_email_status():
    return await test_smtp_connection()


