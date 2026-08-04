import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv
from itsdangerous import URLSafeSerializer, BadSignature

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
    import time, json, base64
    payload = json.dumps({"email": email, "iat": int(time.time())})
    encoded = base64.urlsafe_b64encode(payload.encode()).rstrip(b"=").decode()
    serializer = URLSafeSerializer(EMAIL_SECRET)
    return serializer.dumps(encoded, salt="email-verify")


def verify_token(token: str, max_age: int = 86400) -> str:
    import time, json, base64
    serializer = URLSafeSerializer(EMAIL_SECRET)
    try:
        raw = serializer.loads(token, salt="email-verify")
    except BadSignature:
        raise ValueError("Invalid verification token")

    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "==="))
        email = payload["email"]
        iat = payload.get("iat", 0)
        if time.time() - iat > max_age:
            raise ValueError("Verification link has expired")
        return email
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError):
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
