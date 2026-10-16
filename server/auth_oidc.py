"""Pocket ID（OIDC）登录。未配置 issuer 时整段关闭，本地开发不受影响。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse, Response

_COOKIE = "fl_session"
_STATE_COOKIE = "fl_oidc"
_TTL = 14 * 24 * 3600


def enabled() -> bool:
    return bool(os.environ.get("FLIGHTLOG_OIDC_ISSUER", "").strip())


def _secret() -> bytes:
    raw = os.environ.get("FLIGHTLOG_SESSION_SECRET", "").strip()
    if not raw:
        raise HTTPException(500, "未设置 FLIGHTLOG_SESSION_SECRET")
    return raw.encode()


def _issuer() -> str:
    return os.environ["FLIGHTLOG_OIDC_ISSUER"].rstrip("/")


def _client_id() -> str:
    return os.environ["FLIGHTLOG_OIDC_CLIENT_ID"].strip()


def _client_secret() -> str:
    return os.environ["FLIGHTLOG_OIDC_CLIENT_SECRET"].strip()


def _allowed() -> set[str]:
    raw = os.environ.get("FLIGHTLOG_OIDC_ALLOWED_EMAILS", "")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _hosts() -> set[str]:
    raw = os.environ.get("FLIGHTLOG_OIDC_HOSTS", "")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def _unsign(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expect = hmac.new(_secret(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expect), sig):
            return None
        data = json.loads(_unb64(body))
        if int(data.get("exp", 0)) < int(time.time()):
            return None
        return data
    except (ValueError, json.JSONDecodeError):
        return None


def session_email(request: Request) -> str | None:
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    data = _unsign(token)
    if not data:
        return None
    return data.get("email") or None


def public_origin(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    host = host.split(",")[0].strip()
    return f"{proto}://{host}".rstrip("/")


def _host_ok(request: Request) -> bool:
    allow = _hosts()
    if not allow:
        return True
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "")
    host = host.split(",")[0].strip().split(":")[0].lower()
    return host in allow


def _redirect_uri(request: Request) -> str:
    return public_origin(request) + "/api/auth/callback"


def _secure(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto == "https"


async def _discovery() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_issuer()}/.well-known/openid-configuration")
        r.raise_for_status()
        return r.json()


async def login(request: Request) -> RedirectResponse:
    if not _host_ok(request):
        raise HTTPException(400, "主机名不在允许的登录回调列表")
    disc = await _discovery()
    verifier = secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(18)
    params = {
        "client_id": _client_id(),
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": _redirect_uri(request),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = disc["authorization_endpoint"] + "?" + urlencode(params)
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(
        _STATE_COOKIE,
        _sign({"state": state, "nonce": nonce, "verifier": verifier, "exp": int(time.time()) + 600}),
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        max_age=600,
        path="/",
    )
    return resp


async def callback(request: Request) -> RedirectResponse:
    err = request.query_params.get("error")
    if err:
        raise HTTPException(400, request.query_params.get("error_description") or err)
    code = request.query_params.get("code") or ""
    state = request.query_params.get("state") or ""
    saved = _unsign(request.cookies.get(_STATE_COOKIE) or "")
    if not saved or saved.get("state") != state or not code:
        raise HTTPException(400, "登录状态无效，请重试")
    disc = await _discovery()
    async with httpx.AsyncClient(timeout=20) as client:
        token = await client.post(
            disc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(request),
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "code_verifier": saved["verifier"],
            },
        )
        if token.status_code >= 400:
            raise HTTPException(400, "换取令牌失败")
        access = token.json().get("access_token")
        info = await client.get(
            disc["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access}"},
        )
        info.raise_for_status()
        profile = info.json()
    email = (profile.get("email") or "").strip().lower()
    allow = _allowed()
    if allow and email not in allow:
        raise HTTPException(403, "该账号不在允许列表")
    if not email:
        raise HTTPException(400, "Pocket ID 未返回邮箱")
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(_STATE_COOKIE, path="/")
    resp.set_cookie(
        _COOKIE,
        _sign({"email": email, "exp": int(time.time()) + _TTL}),
        httponly=True,
        secure=_secure(request),
        samesite="lax",
        max_age=_TTL,
        path="/",
    )
    return resp


def logout(request: Request) -> RedirectResponse:
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(_COOKIE, path="/")
    return resp


def require(request: Request) -> Response | None:
    """已登录返回 None；否则返回应直接发出的响应。"""
    if not enabled():
        return None
    path = request.url.path
    if path in ("/api/health", "/api/auth/login", "/api/auth/callback", "/api/auth/logout"):
        return None
    if path.startswith(("/css/", "/js/", "/fonts/")):
        return None
    if session_email(request):
        return None
    if path.startswith("/api/"):
        return Response(
            content='{"detail":"需要登录"}',
            status_code=401,
            media_type="application/json",
        )
    return RedirectResponse("/api/auth/login", status_code=302)
