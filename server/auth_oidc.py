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


def cf_access_email(request: Request) -> str | None:
    """Cloudflare Access 边缘已认证时注入的邮箱（免二次 OIDC）。"""
    raw = (
        request.headers.get("cf-access-authenticated-user-email")
        or request.headers.get("Cf-Access-Authenticated-User-Email")
        or ""
    ).strip().lower()
    if not raw:
        return None
    allow = _allowed()
    if allow and raw not in allow:
        return None
    return raw


def session_email(request: Request) -> str | None:
    token = request.cookies.get(_COOKIE)
    if token:
        data = _unsign(token)
        if data:
            return data.get("email") or None
    return cf_access_email(request)


def _configured_public_origin() -> str | None:
    raw = os.environ.get("FLIGHTLOG_PUBLIC_ORIGIN", "").strip()
    if not raw:
        return None
    return raw.rstrip("/")


def _request_host(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return host.split(",")[0].strip()


def _request_hostname(request: Request) -> str:
    return _request_host(request).split(":")[0].lower()


def public_origin(request: Request) -> str:
    configured = _configured_public_origin()
    if configured:
        return configured
    host = _request_host(request)
    if not host:
        return str(request.base_url).rstrip("/")
    fwd_proto = request.headers.get("x-forwarded-proto")
    if fwd_proto:
        proto = fwd_proto.split(",")[0].strip()
    elif _request_hostname(request) in _hosts():
        proto = "https"
    else:
        proto = request.url.scheme
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
    configured = _configured_public_origin()
    if configured:
        return configured.lower().startswith("https://")
    fwd_proto = request.headers.get("x-forwarded-proto")
    if fwd_proto:
        return fwd_proto.split(",")[0].strip() == "https"
    if _request_hostname(request) in _hosts():
        return True
    return request.url.scheme == "https"


async def _discovery() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{_issuer()}/.well-known/openid-configuration")
        r.raise_for_status()
        return r.json()


def _safe_next(request: Request) -> str:
    raw = (request.query_params.get("next") or "/").strip()
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw


async def login(request: Request) -> RedirectResponse:
    if not _host_ok(request):
        raise HTTPException(400, "主机名不在允许的登录回调列表")
    disc = await _discovery()
    verifier = secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(18)
    next_url = _safe_next(request)
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
        _sign({
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "next": next_url,
            "exp": int(time.time()) + 600,
        }),
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
    next_url = saved.get("next") or "/"
    if not isinstance(next_url, str) or not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    resp = RedirectResponse(next_url, status_code=302)
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


def status_payload(request: Request) -> dict:
    en = enabled()
    email = session_email(request) if en else None
    out = {
        "oidc": en,
        "authenticated": (not en) or bool(email),
    }
    if email:
        out["email"] = email
    return out


def logout(request: Request) -> RedirectResponse:
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(_COOKIE, path="/")
    return resp



def mint_session_from_cf_access(request: Request) -> RedirectResponse | None:
    """若仅有 CF Access 身份、尚无应用 cookie，签发 14 天会话并刷新当前页。"""
    if request.cookies.get(_COOKIE):
        return None
    email = cf_access_email(request)
    if not email:
        return None
    if request.url.path.startswith("/api/"):
        return None
    resp = RedirectResponse(str(request.url.path) or "/", status_code=302)
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


def require(request: Request) -> Response | None:
    """已登录返回 None；否则返回应直接发出的响应。"""
    if not enabled():
        return None
    path = request.url.path
    if path in (
        "/api/health",
        "/api/auth/login",
        "/api/auth/callback",
        "/api/auth/logout",
        "/api/auth/status",
    ):
        return None
    if path.startswith(("/css/", "/js/", "/fonts/")):
        return None
    minted = mint_session_from_cf_access(request)
    if minted is not None:
        return minted
    if session_email(request):
        return None
    if path.startswith("/api/"):
        return Response(
            content='{"detail":"需要登录"}',
            status_code=401,
            media_type="application/json",
        )
    return RedirectResponse("/api/auth/login", status_code=302)
