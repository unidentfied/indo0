import os
import logging
from pathlib import Path
from dotenv import load_dotenv
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

_ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

logger = logging.getLogger("sindio.email")

EMAIL_SECRET = os.getenv("EMAIL_SECRET", "sindio-email-dev-secret-change-in-production")
# FRONTEND_VERIFY_URL must be set to the deployed frontend domain in production
# (e.g. https://sindio.net/verify-email) so verification emails contain the correct link.
FRONTEND_VERIFY_URL = os.getenv("FRONTEND_VERIFY_URL", "https://sindio.net/verify-email")


def _get_mail_config():
    """Lazily create the FastMail ConnectionConfig to avoid importing
    fastapi_mail at module level (it has a pydantic SecretStr bug in some versions)."""
    from fastapi_mail import ConnectionConfig
    return ConnectionConfig(
        MAIL_USERNAME=os.getenv("MAIL_USERNAME"),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
        MAIL_FROM=os.getenv("MAIL_FROM", os.getenv("MAIL_USERNAME")),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp-relay.brevo.com"),
        MAIL_TLS=os.getenv("MAIL_TLS", "True").lower() == "true",
        MAIL_SSL=os.getenv("MAIL_SSL", "False").lower() == "true",
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True,
    )


# Serializer for time-limited tokens (default 24 h)
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
    await fm.send_message(message)
