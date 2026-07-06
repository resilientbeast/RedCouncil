"""
Clerk JWT verification for protected API endpoints.

This is the REAL security boundary, not the frontend route guard. A React
router redirect only changes what's rendered in a browser -- anyone can call
`curl -X POST /api/v1/decisions` directly and bypass it entirely. This
module is what actually stops an unauthenticated request from reaching a
Qwen API call (and therefore from burning API credits).

Verifies the Bearer token Clerk issues to signed-in users against Clerk's
JWKS endpoint (cached, since JWKS keys rotate rarely), checking signature,
issuer, and expiry via standard RS256 JWT verification. No Clerk SDK
dependency needed -- this is plain JWT verification against a public JWKS,
which is all Clerk's session tokens require.

EventSource (used for the SSE stream endpoint) cannot set custom headers in
any browser, so that one endpoint accepts the token as a `?token=` query
parameter instead of an Authorization header -- see verify_clerk_token's
`token_override` parameter. This is a standard, widely-used workaround for
that specific browser API limitation, not a weaker verification path; the
same signature/issuer/expiry checks apply either way.
"""

from __future__ import annotations

import time

import httpx
from fastapi import HTTPException, Request
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

_jwks_cache: dict | None = None
_jwks_cache_time: float = 0.0
_JWKS_TTL_SECONDS = 3600  # Clerk's signing keys rotate rarely; an hour is generous, not tight


async def _get_jwks() -> dict:
    global _jwks_cache, _jwks_cache_time
    if _jwks_cache is None or (time.time() - _jwks_cache_time) > _JWKS_TTL_SECONDS:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.clerk_issuer}/.well-known/jwks.json")
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_cache_time = time.time()
    return _jwks_cache


def _reset_jwks_cache() -> None:
    """Test-only escape hatch -- production code never needs to call this."""
    global _jwks_cache, _jwks_cache_time
    _jwks_cache = None
    _jwks_cache_time = 0.0


async def verify_token_string(token: str) -> str:
    """
    Verifies a raw JWT string against Clerk's JWKS. Returns the Clerk
    user_id (the token's `sub` claim) on success. Raises HTTPException(401)
    on any failure -- expired token, bad signature, wrong issuer, unknown
    key id, or malformed input. Shared by both auth paths (header and query
    param) so there's exactly one place that does the actual verification.
    """
    try:
        jwks = await _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        key = next((k for k in jwks["keys"] if k["kid"] == unverified_header.get("kid")), None)
        if key is None:
            raise HTTPException(401, "Unknown signing key")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"verify_aud": False},  # Clerk session tokens don't set `aud` by default
        )
        return payload["sub"]
    except HTTPException:
        raise
    except JWTError as exc:
        raise HTTPException(401, f"Invalid or expired token: {exc}") from exc
    except (KeyError, httpx.HTTPError) as exc:
        raise HTTPException(401, f"Token verification failed: {exc}") from exc


async def verify_clerk_token(request: Request) -> str:
    """
    Standard FastAPI dependency for header-based auth:
        Authorization: Bearer <token>
    Use this on every endpoint reachable via fetch()/XHR -- i.e. everything
    except the SSE stream endpoint, which needs verify_clerk_token_query
    instead (see module docstring).
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(401, "Empty bearer token")
    return await verify_token_string(token)


async def verify_clerk_token_query(request: Request) -> str:
    """
    Query-parameter variant for the one endpoint that can't use headers:
    the SSE stream, opened via the browser's native EventSource, which has
    no API for setting custom headers. Same verification, different place
    to find the token -- not a weaker check.
    """
    token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(401, "Missing token query parameter")
    return await verify_token_string(token)
