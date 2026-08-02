import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType

# Load environment variables (should be set in .env or system)
EMAIL_SECRET = os.getenv("EMAIL_SECRET")
FRONTEND_VERIFY_URL = os.getenv("FRONTEND_VERIFY_URL", "http://localhost:3000/verify-email")

# FastMail configuration – all required settings must exist in environment
conf = ConnectionConfig(
    MAIL_USERNAME=os.getenv("MAIL_USERNAME""),
    MAIL_PASSWORD=os.getenv("MAIL_PASSWORD"),
    MAIL_FROM=os.getenv("MAIL_FROM", os.getenv("MAIL_USERNAME")),
    MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
    MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp-relay.brevo.com"),
    MAIL_TLS=os.getenv("MAIL_TLS", "True").lower() == "true",
    MAIL_SSL=os.getenv("MAIL_SSL", "False").lower() == "true",
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True,
)

# Serializer for time‑limited tokens (default 24 h)
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
    verify_link = f"{FRONTEND_VERIFY_URL}?token={token}"
    message = MessageSchema(
        subject="Verify your Sindio account",
        recipients=[to_email],
        body=f"Hello,\n\nPlease verify your account by clicking the link below (valid for 24 hours):\n{verify_link}\n\nIf you did not sign up for Sindio, you can safely ignore this email.",
        subtype=MessageType.plain,
    )
    fm = FastMail(conf)
    await fm.send_message(message)
