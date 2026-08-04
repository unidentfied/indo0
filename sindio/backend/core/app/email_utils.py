import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

logger = logging.getLogger("sindio.email")

EMAIL_SECRET = os.getenv("EMAIL_SECRET", "sindio-email-dev-secret-change-in-production")
FRONTEND_VERIFY_URL = os.getenv("FRONTEND_VERIFY_URL", "https://sindio.net/verify-email")


def _get_mail_config():
    from fastapi_mail import ConnectionConfig
    return ConnectionConfig(
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_FROM=os.getenv("MAIL_FROM", os.getenv("MAIL_USERNAME")),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp-relay.brevo.com"),
        MAIL_STARTTLS=os.getenv("MAIL_TLS", "True").lower() == "true",
        MAIL_SSL_TLS=os.getenv("MAIL_SSL", "False").lower() == "true",
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )


def generate_verification_token(email: str) -> str:
    serializer = URLSafeTimedSerializer(EMAIL_SECRET)
    return serializer.dumps(email, salt="email-verify")


def verify_token(token: str, max_age: int = 86400) -> str:
    serializer = URLSafeTimedSerializer(EMAIL_SECRET)
    try:
        email = serializer.loads(token, salt="email-verify", max_age=max_age)
        return email
    except SignatureExpired:
        raise ValueError("Verification link has expired")
    except BadSignature:
        raise ValueError("Invalid verification token")


async def send_verification_email(to_email: str, token: str) -> None:
    from fastapi_mail import FastMail, MessageSchema, MessageType
    verify_link = f"{FRONTEND_VERIFY_URL}?token={token}"
    message = MessageSchema(
        subject="Verify your Sindio account",
        recipients=[to_email],
        body=f"Hello,\n\nPlease verify your account by clicking the link below (valid for 24 hours):\n{verify_link}\n\nIf you did not sign up for Sindio, you can safely ignore this email.",
        subtype=MessageType.plain,
    )
    conf = _get_mail_config()
    fm = FastMail(conf)

    last_error = None
    for attempt in range(1, 4):
        try:
            await fm.send_message(message)
            logger.info("verification_email_sent", email=to_email, attempt=attempt)
            return
        except Exception as exc:
            last_error = exc
            logger.warning("verification_email_attempt_failed", email=to_email, attempt=attempt, error=str(exc))
            if attempt < 3:
                await asyncio.sleep(2 ** attempt)

    logger.error("verification_email_failed_after_retries", email=to_email, error=str(last_error))
    raise last_error
