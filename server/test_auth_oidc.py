"""OIDC 回调 URL 在反向代理后的 public origin 解析。"""

import os
from contextlib import contextmanager

from starlette.requests import Request

import auth_oidc as auth


@contextmanager
def _env(**kwargs: str | None):
    saved: dict[str, str | None] = {}
    for key, value in kwargs.items():
        saved[key] = os.environ.get(key)
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        yield
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def _request(
    *,
    host: str = "flightlog.alexander.xin",
    scheme: str = "http",
    forwarded_proto: str | None = None,
    forwarded_host: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"host", host.encode())]
    if forwarded_proto is not None:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    if forwarded_host is not None:
        headers.append((b"x-forwarded-host", forwarded_host.encode()))
    hostname = host.split(":")[0]
    port = 443 if scheme == "https" else 80
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": headers,
        "scheme": scheme,
        "server": (hostname, port),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def test_redirect_uri_uses_configured_public_origin():
    with _env(FLIGHTLOG_PUBLIC_ORIGIN="https://flightlog.alexander.xin"):
        req = _request(scheme="http")
        assert auth._redirect_uri(req) == "https://flightlog.alexander.xin/api/auth/callback"


def test_redirect_uri_honors_forwarded_proto():
    with _env(FLIGHTLOG_PUBLIC_ORIGIN=None):
        req = _request(scheme="http", forwarded_proto="https")
        assert auth._redirect_uri(req) == "https://flightlog.alexander.xin/api/auth/callback"


def test_redirect_uri_https_for_oidc_host_without_forwarded():
    with _env(FLIGHTLOG_PUBLIC_ORIGIN=None, FLIGHTLOG_OIDC_HOSTS="flightlog.alexander.xin"):
        req = _request(scheme="http")
        assert auth._redirect_uri(req) == "https://flightlog.alexander.xin/api/auth/callback"


def test_redirect_uri_plain_http_when_no_hints():
    with _env(FLIGHTLOG_PUBLIC_ORIGIN=None, FLIGHTLOG_OIDC_HOSTS=None):
        req = _request(host="localhost:8321", scheme="http")
        assert auth._redirect_uri(req) == "http://localhost:8321/api/auth/callback"


def _request_with_query(query: str, **kwargs) -> Request:
    scope = _request(**kwargs).scope
    scope["query_string"] = query.encode()
    return Request(scope)


def test_safe_next_accepts_relative_path():
    req = _request_with_query("next=%2F%23logbook")
    assert auth._safe_next(req) == "/#logbook"


def test_safe_next_rejects_open_redirect():
    req = _request_with_query("next=https%3A%2F%2Fevil.example")
    assert auth._safe_next(req) == "/"


if __name__ == "__main__":
    test_redirect_uri_uses_configured_public_origin()
    test_redirect_uri_honors_forwarded_proto()
    test_redirect_uri_https_for_oidc_host_without_forwarded()
    test_redirect_uri_plain_http_when_no_hints()
    test_safe_next_accepts_relative_path()
    test_safe_next_rejects_open_redirect()
    print("auth_oidc tests OK")
