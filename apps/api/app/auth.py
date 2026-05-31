"""JWT cookie session — same algorithm + secret as the previous Node `jose` impl so
cookies set by the legacy code continue to validate, and vice versa."""

from __future__ import annotations

import hashlib
import time
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Response

from app.config import get_settings
from app.errors import Unauthorized

ALG = "HS256"
SESSION_SUBJECT = "admin"


def create_session_token() -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": SESSION_SUBJECT,
        "iat": now,
        "exp": now + settings.session_lifetime_seconds,
    }
    return jwt.encode(payload, settings.auth_secret, algorithm=ALG)


def verify_session_token(token: str) -> bool:
    try:
        jwt.decode(token, get_settings().auth_secret, algorithms=[ALG])
        return True
    except jwt.PyJWTError:
        return False


def check_admin_password(password: str) -> bool:
    expected = get_settings().admin_password_hash.lower()
    got = hashlib.sha256(password.encode("utf-8")).hexdigest().lower()
    return _timing_safe_eq(expected, got)


def _timing_safe_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    diff = 0
    for x, y in zip(a, b):
        diff |= ord(x) ^ ord(y)
    return diff == 0


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.app_env != "dev",
        max_age=settings.session_lifetime_seconds,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(key=settings.session_cookie_name, path="/")


def get_current_user(
    plumeai_session: Annotated[str | None, Cookie()] = None,
) -> str:
    """FastAPI dependency: returns the session subject or raises Unauthorized.

    The cookie name `plumeai_session` matches `settings.session_cookie_name`. We hardcode
    it in the parameter annotation so FastAPI's docs render the dependency correctly.
    """
    if not plumeai_session or not verify_session_token(plumeai_session):
        raise Unauthorized("Authentication required.")
    return SESSION_SUBJECT


CurrentUser = Annotated[str, Depends(get_current_user)]
