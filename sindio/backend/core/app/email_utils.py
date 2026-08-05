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
logger.setLevel(logging.DEBUG if os.getenv("LOG_LEVEL", "info").lower() == "debug" else logging.INFO)

if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    logger.addHandler(_handler)

EMAIL_SECRET = os.getenv("EMAIL_SECRET", "sindio-email-dev-secret-change-in-production")
FRONTEND_VERIFY_URL = os.getenv("FRONTEND_VERIFY_URL", "https://sindio.net/verify-email")
MAIL_FROM = os.getenv("MAIL_FROM", "Sindio <noreply@sindio.net>")
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"


def _parse_from(full_from: str) -> tuple[str, str]:
    if "<" in full_from and ">" in full_from:
        name = full_from[: full_from.index("<")].strip()
        email = full_from[full_from.index("<") + 1 : full_from.index(">")].strip()
        return name, email
    return "Sindio", full_from.strip()


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
    if not BREVO_API_KEY:
        raise RuntimeError("BREVO_API_KEY is not configured")

    from httpx import AsyncClient, HTTPError

    verify_link = f"{FRONTEND_VERIFY_URL}?token={token}"
    sender_name, sender_email = _parse_from(MAIL_FROM)

    payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": to_email}],
        "subject": "Verify your Sindio account",
        "textContent": (
            f"Hello,\n\n"
            f"Please verify your account by clicking the link below (valid for 24 hours):\n"
            f"{verify_link}\n\n"
            f"If you did not sign up for Sindio, you can safely ignore this email."
        ),
    }

    last_error = None
    for attempt in range(1, 4):
        try:
            async with AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    BREVO_API_URL,
                    json=payload,
                    headers={
                        "api-key": BREVO_API_KEY,
                        "Content-Type": "application/json",
                    },
                )
                if resp.status_code in (200, 201, 202):
                    logger.info("verification_email_sent to=%s attempt=%d status=%d", to_email, attempt, resp.status_code)
                    return
                error_body = resp.text
                logger.warning(
                    "verification_email_attempt_failed to=%s attempt=%d status=%d body=%s",
                    to_email, attempt, resp.status_code, error_body[:500],
                )
                last_error = RuntimeError(f"Brevo API returned {resp.status_code}: {error_body[:200]}")
        except HTTPError as exc:
            last_error = exc
            logger.warning("verification_email_attempt_failed to=%s attempt=%d error=%s", to_email, attempt, exc)

        if attempt < 3:
            await asyncio.sleep(2 ** attempt)

    logger.error("verification_email_failed_after_retries to=%s error=%s", to_email, last_error)
    raise last_error


async def test_smtp_connection() -> dict:

    mail_keys = sorted([k for k in os.environ.keys() if k.upper().startswith("MAIL")])
    brevo_keys = sorted([k for k in os.environ.keys() if k.upper().startswith("BREVO")])

    result = {
        "api_configured": bool(BREVO_API_KEY),
        "from_address": MAIL_FROM,
        "mail_env_keys": mail_keys,
        "brevo_env_keys": brevo_keys,
        "host": os.getenv("PORT", "unknown"),
        "is_core": os.getenv("PORT") == "8081",
        "api_test": {},
    }

    if not BREVO_API_KEY:
        result["api_test"]["error"] = "BREVO_API_KEY is not configured"
        return result

    from httpx import AsyncClient, HTTPError

    sender_name, sender_email = _parse_from(MAIL_FROM)
    test_payload = {
        "sender": {"name": sender_name, "email": sender_email},
        "to": [{"email": sender_email}],
        "subject": "Sindio Email Test",
        "textContent": "This is a connectivity test from Sindio.",
    }

    try:
        async with AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                BREVO_API_URL,
                json=test_payload,
                headers={"api-key": BREVO_API_KEY, "Content-Type": "application/json"},
            )
            result["api_test"]["status"] = resp.status_code
            result["api_test"]["body"] = resp.text[:500]
            result["api_test"]["ok"] = resp.status_code in (200, 201, 202)
    except HTTPError as exc:
        result["api_test"]["error"] = str(exc)
    except Exception as exc:
        result["api_test"]["error"] = str(exc)

    return result
