import os
import asyncio
import logging
import socket
from pathlib import Path
from dotenv import load_dotenv
from itsdangerous import URLSafeSerializer, BadSignature

_ENV_PATH = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

logger = logging.getLogger("sindio.email")
logger.setLevel(logging.DEBUG if os.getenv("LOG_LEVEL", "info").lower() == "debug" else logging.INFO)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)

EMAIL_SECRET = os.getenv("EMAIL_SECRET", "sindio-email-dev-secret-change-in-production")
FRONTEND_VERIFY_URL = os.getenv("FRONTEND_VERIFY_URL", "https://sindio.net/verify-email")

MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp-relay.brevo.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_FROM = os.getenv("MAIL_FROM", os.getenv("MAIL_USERNAME", ""))


def _get_mail_config():
    from fastapi_mail import ConnectionConfig

    use_tls = os.getenv("MAIL_TLS", "True").lower() == "true"
    use_ssl = os.getenv("MAIL_SSL", "False").lower() == "true"

    try:
        return ConnectionConfig(
            MAIL_USERNAME=MAIL_USERNAME,
            MAIL_PASSWORD=MAIL_PASSWORD,
            MAIL_FROM=MAIL_FROM,
            MAIL_PORT=MAIL_PORT,
            MAIL_SERVER=MAIL_SERVER,
            MAIL_STARTTLS=use_tls,
            MAIL_SSL_TLS=use_ssl,
            USE_CREDENTIALS=True,
            VALIDATE_CERTS=True,
        )
    except TypeError:
        logger.warning("fastapi-mail does not support MAIL_STARTTLS/MAIL_SSL_TLS, falling back to MAIL_TLS/MAIL_SSL")
        return ConnectionConfig(
            MAIL_USERNAME=MAIL_USERNAME,
            MAIL_PASSWORD=MAIL_PASSWORD,
            MAIL_FROM=MAIL_FROM,
            MAIL_PORT=MAIL_PORT,
            MAIL_SERVER=MAIL_SERVER,
            MAIL_TLS=use_tls,
            MAIL_SSL=use_ssl,
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
            logger.info("verification_email_sent to=%s attempt=%d", to_email, attempt)
            return
        except Exception as exc:
            last_error = exc
            logger.warning("verification_email_attempt_failed to=%s attempt=%d error=%s", to_email, attempt, exc)
            if attempt < 3:
                await asyncio.sleep(2 ** attempt)

    logger.error("verification_email_failed_after_retries to=%s error=%s", to_email, last_error)
    raise last_error


async def test_smtp_connection() -> dict:
    result = {"smtp_reachable": False, "authenticated": False, "error": None, "config": {}}

    result["config"] = {
        "server": MAIL_SERVER,
        "port": MAIL_PORT,
        "username_set": bool(MAIL_USERNAME),
        "password_set": bool(MAIL_PASSWORD),
        "from": MAIL_FROM,
    }

    if not MAIL_USERNAME or not MAIL_PASSWORD:
        result["error"] = "MAIL_USERNAME or MAIL_PASSWORD is not configured"
        return result

    try:
        sock = socket.create_connection((MAIL_SERVER, MAIL_PORT), timeout=10)
        sock.close()
        result["smtp_reachable"] = True
    except Exception as exc:
        result["error"] = f"SMTP server {MAIL_SERVER}:{MAIL_PORT} unreachable: {exc}"
        return result

    try:
        from fastapi_mail import FastMail, MessageSchema, MessageType
        conf = _get_mail_config()
        fm = FastMail(conf)
        test_msg = MessageSchema(
            subject="Sindio SMTP Test",
            recipients=[MAIL_FROM.replace("<", "").replace(">", "").split()[-1] if "<" in MAIL_FROM else MAIL_USERNAME],
            body="This is an SMTP connectivity test from Sindio.",
            subtype=MessageType.plain,
        )
        await fm.send_message(test_msg)
        result["authenticated"] = True
    except Exception as exc:
        result["error"] = f"SMTP auth/send failed: {exc}"

    return result
