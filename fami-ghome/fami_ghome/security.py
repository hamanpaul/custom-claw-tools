from __future__ import annotations

from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import secrets


class PasswordHashError(RuntimeError):
    """Raised when a password hash cannot be parsed or verified."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    target = (value or utcnow()).astimezone(timezone.utc)
    return target.isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = f"{value[:-1]}+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def expires_in(seconds: int) -> str:
    return utc_iso(utcnow() + timedelta(seconds=seconds))


def expires_in_days(days: int) -> str:
    return utc_iso(utcnow() + timedelta(days=days))


def _urlsafe_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _urlsafe_b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def make_password_hash(password: str, *, salt: bytes | None = None, n: int = 2**14, r: int = 8, p: int = 1) -> str:
    if not password:
        raise PasswordHashError("password must not be empty")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=64)
    return f"scrypt${n}${r}${p}${_urlsafe_b64(salt)}${_urlsafe_b64(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    if not stored_hash:
        raise PasswordHashError("AUTH_ADMIN_PASSWORD_HASH is empty")
    parts = stored_hash.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        raise PasswordHashError("unsupported password hash format; expected scrypt$N$r$p$salt$digest")
    _scheme, n_raw, r_raw, p_raw, salt_raw, digest_raw = parts
    salt = _urlsafe_b64_decode(salt_raw)
    expected = _urlsafe_b64_decode(digest_raw)
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=int(n_raw),
        r=int(r_raw),
        p=int(p_raw),
        dklen=len(expected),
    )
    return hmac.compare_digest(actual, expected)


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(secret: str, token: str) -> str:
    if not secret:
        raise PasswordHashError("secret must not be empty")
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
