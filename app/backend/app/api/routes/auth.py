"""
Sign-in API: cookie sessions for the web app.

POST /auth/login     {username, password} -> sets an HttpOnly, SameSite=Strict session cookie
POST /auth/logout    clears the cookie
GET  /auth/me        current user (401 when signed out)
POST /auth/password  change own password (revokes all other sessions)
Accounts are created by an administrator: python scripts/manage_users.py (no self-registration).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import (COOKIE_NAME, User, audit, client_ip, current_user, issue_guest, issue_token, limiter, login_locked,
                               normalise_username, rate_key_ip, record_login_failure, revoke_token, user_store)

log = logging.getLogger("app.security")
router = APIRouter(prefix="/auth")


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class PasswordIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=settings.session_ttl_s, httponly=True, secure=settings.cookie_secure,
                        samesite="strict", path="/")


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response) -> dict:
    if settings.auth_mode == "disabled_local_dev":
        return {"username": "local-dev", "role": "admin", "auth_mode": settings.auth_mode}
    ip = client_ip(request)
    try:
        name = normalise_username(body.username)
    except ValueError:
        name = "invalid"
    # account+network lockout, an account-wide cap across all networks, and a per-network cap against password spraying
    if login_locked(name, ip):
        log.warning("login locked out user=%s ip=%s", name, ip)
        audit("login_locked_out", name, ip)
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed sign-ins. Try again later.")
    user = user_store().authenticate(body.username, body.password)
    if user is None:
        record_login_failure(name, ip)
        log.warning("login failed user=%s ip=%s", name, ip)
        audit("login_failed", name, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    limiter.reset(f"login:{name}:{rate_key_ip(ip)}")
    _set_cookie(response, issue_token(user, settings.secret_key, settings.session_ttl_s))
    log.info("login ok user=%s ip=%s", user.username, ip)
    audit("login_ok", user.username, ip)
    return {"username": user.username, "role": user.role}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict:
    revoke_token(request.cookies.get(COOKIE_NAME, ""))
    response.delete_cookie(COOKIE_NAME, path="/")
    from app.records.store import get_records

    get_records().log(getattr(request.state, "username", None), "sign_out", summary="signed out")
    return {"signed_out": True}


@router.get("/me")
async def me(request: Request, response: Response) -> dict:
    try:
        user = current_user(request)
    except HTTPException:
        if settings.auth_mode != "public_demo":
            raise
        # open testing: a new browser gets its own private guest space, no login screen
        net = rate_key_ip(client_ip(request))
        if not limiter.hit(f"guest-new:{net}", settings.guests_per_ip_per_hour, 3600):
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many new visitors from this network; try again later")
        user = issue_guest(response)
        audit("guest_created", user.username, client_ip(request))
    records_visible = user.role == "admin" or (settings.auth_mode == "public_demo" and settings.public_records)
    return {"username": user.username, "role": user.role, "auth_mode": settings.auth_mode, "records_visible": records_visible}


@router.post("/password")
async def change_password(body: PasswordIn, request: Request, response: Response, user: User = Depends(current_user)) -> dict:
    store = user_store()
    if login_locked(user.username, client_ip(request)):   # audit L-03: this endpoint is also a password oracle
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong passwords. Try again later.")
    if store.authenticate(user.username, body.current_password) is None:
        record_login_failure(user.username, client_ip(request))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong")
    try:
        store.update(user.username, password=body.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit("password_changed", user.username, client_ip(request))
    refreshed = store.user(user.username)
    _set_cookie(response, issue_token(refreshed, settings.secret_key, settings.session_ttl_s))
    return {"changed": True}
