"""Phase 1 access control: a shared bearer token between the Next.js server and this API.

The browser never sees the token: the Next.js route handler (/api/backend/*) injects it server-side.
Phase 6 adds user accounts, roles and session auth on top of this.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, Query, status

from .config import get_settings


def require_token(x_academy_token: str | None = Header(default=None),
                  authorization: str | None = Header(default=None),
                  token: str | None = Query(default=None, include_in_schema=False)) -> None:
    expected = get_settings().api_token
    supplied = x_academy_token or token
    if not supplied and authorization and authorization.lower().startswith("bearer "):
        supplied = authorization[7:]
    if not supplied or not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing API token")
