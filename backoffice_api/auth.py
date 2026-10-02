"""Backoffice login: scrypt password hashes and an HMAC-signed session cookie (stdlib only).

The cookie holds "<admin id>.<expiry>.<signature>". Every request reloads the
admin from the DB, so deactivating an account locks it out immediately.
"""

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select

from app import audit
from app.audit import Action
from app.db.models.admin_user import AdminUser
from app.db.session import SessionLocal

COOKIE = "bo_session"
SESSION_SECONDS = 12 * 3600
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60

SECRET = os.environ.get("BACKOFFICE_SECRET", "")
if len(SECRET) < 32:
    raise RuntimeError("BACKOFFICE_SECRET must be set to at least 32 random characters")

# Only over HTTPS; off by default because the backoffice may be reached over plain HTTP on the LAN.
COOKIE_SECURE = os.environ.get("BACKOFFICE_COOKIE_SECURE", "false").lower() == "true"

# ponytail: in-memory per-process lockout; move to Redis if the API runs several workers
_failures: dict[str, list[float]] = {}


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return "$".join(["scrypt", str(_N), str(_R), str(_P), _b64(salt), _b64(digest)])


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p))
    except ValueError:
        return False
    return hmac.compare_digest(actual, _unb64(digest))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------
# Session token
# --------------------------------------------------------------------------


def _sign(payload: str) -> str:
    return _b64(hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(admin_id: int) -> str:
    payload = f"{admin_id}.{int(time.time()) + SESSION_SECONDS}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> int | None:
    try:
        admin_id, expiry, signature = token.split(".")
    except ValueError:
        return None

    if not hmac.compare_digest(signature, _sign(f"{admin_id}.{expiry}")) or int(expiry) < time.time():
        return None
    return int(admin_id)


# --------------------------------------------------------------------------
# Login / request guards
# --------------------------------------------------------------------------


def _locked(username: str) -> bool:
    recent = [t for t in _failures.get(username, []) if time.time() - t < LOCKOUT_SECONDS]
    _failures[username] = recent
    return len(recent) >= MAX_FAILURES


async def login(username: str, password: str, response: Response) -> AdminUser:
    username = username.strip().lower()

    if _locked(username):
        raise HTTPException(429, "เข้าสู่ระบบผิดหลายครั้ง กรุณารอ 15 นาทีแล้วลองใหม่")

    async with SessionLocal() as session:
        admin = await session.scalar(select(AdminUser).where(AdminUser.username == username))

        if not admin or not admin.active or not verify_password(password, admin.password_hash):
            _failures.setdefault(username, []).append(time.time())
            audit.add(session, Action.ADMIN_LOGIN_FAILED, actor=audit.admin(username[:64]))
            await session.commit()
            raise HTTPException(401, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

        _failures.pop(username, None)
        admin.last_login_at = datetime.now(timezone.utc)
        audit.add(session, Action.ADMIN_LOGIN, actor=audit.admin(admin.username))
        await session.commit()

    response.set_cookie(
        COOKIE,
        make_token(admin.id),
        max_age=SESSION_SECONDS,
        httponly=True,
        samesite="strict",
        secure=COOKIE_SECURE,
    )
    return admin


def logout(response: Response) -> None:
    response.delete_cookie(COOKIE)


async def current_admin(request: Request) -> AdminUser:
    admin_id = read_token(request.cookies.get(COOKIE, ""))

    if admin_id is None:
        raise HTTPException(401, "กรุณาเข้าสู่ระบบ")

    # Cross-site forms can't set custom headers; together with SameSite=strict this blocks CSRF.
    if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "backoffice":
        raise HTTPException(403, "Missing X-Requested-With header")

    async with SessionLocal() as session:
        admin = await session.get(AdminUser, admin_id)

    if not admin or not admin.active:
        raise HTTPException(401, "บัญชีนี้ถูกปิดการใช้งาน")
    return admin


async def require_admin(admin: AdminUser = Depends(current_admin)) -> AdminUser:
    """Writes need the admin role; viewers are read-only."""
    if admin.role != "admin":
        raise HTTPException(403, "บัญชีนี้ดูข้อมูลได้อย่างเดียว")
    return admin
