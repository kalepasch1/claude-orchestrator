#!/usr/bin/env python3
"""Authentication, tenancy and request limits for the compliance API.

Round 8 found the gateway took tenancy from the request body:

    tenant_id = body.get("tenant_id", "default")

so any caller could read or mutate any tenant's sandbox by typing a different
string. There was also no caller identity, no request-size bound, no rate
limit, and `Access-Control-Allow-Origin: *` on every response — which on a
loopback service is a browser-reachable path into the whole surface.

The fix is a principal. Every request resolves to a `Principal` first; tenancy
is read **from the principal**, never from the body, and each app resource is
authorized against it.

## Deployment posture

No authentication adapter is configured by default and this module does not
invent one. Until an operator sets one up the gateway stays **loopback-safe**:
requests that demonstrably originate from the local host get the built-in
`local` principal, and everything else is rejected. That keeps the existing
local console working without pretending the surface is authenticated.

Configure real auth by setting `ORCH_COMPLIANCE_API_TOKENS` to a JSON object
mapping token -> {"principal": ..., "tenant": ..., "scopes": [...]}. Tokens are
read from the environment only; nothing is stored in code or in fleet_config
(see the 2026-08-02 plaintext-credential incident). Tokens are compared with
`hmac.compare_digest` and only ever logged as a short salted fingerprint.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, "") or default))
    except (TypeError, ValueError):
        return default


#: 2 MB, matching the fleet-wide API body cap.
MAX_BODY_BYTES = _env_int("ORCH_COMPLIANCE_API_MAX_BODY_BYTES", 2 * 1024 * 1024)
RATE_LIMIT_REQUESTS = _env_int("ORCH_COMPLIANCE_API_RATE_LIMIT", 120)
RATE_LIMIT_WINDOW_S = _env_int("ORCH_COMPLIANCE_API_RATE_WINDOW_S", 60)

#: Empty by default: no origin is trusted until an operator names one. The old
#: `*` is never reachable through this list.
ALLOWED_ORIGINS = tuple(
    o.strip() for o in os.environ.get("ORCH_COMPLIANCE_API_ALLOWED_ORIGINS", "").split(",")
    if o.strip() and o.strip() != "*"
)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"})

READ = "read"
WRITE = "write"
ADMIN = "admin"


@dataclass(frozen=True)
class Principal:
    """An authenticated caller. `tenant` is authoritative for every request."""
    name: str
    tenant: str
    scopes: frozenset = field(default_factory=frozenset)
    via: str = "unknown"

    def may(self, scope: str) -> bool:
        return ADMIN in self.scopes or scope in self.scopes

    def redacted(self) -> dict[str, Any]:
        return {"principal": self.name, "tenant": self.tenant,
                "scopes": sorted(self.scopes), "via": self.via}


class AuthError(Exception):
    """Raised when a request cannot be attributed to a principal."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.status = status


#: The loopback fallback. Deliberately NOT admin: a local caller can read and
#: write its own tenant, but cannot act as another tenant.
LOCAL_PRINCIPAL = Principal(name="local", tenant="default",
                            scopes=frozenset({READ, WRITE}), via="loopback")


def _token_registry() -> dict[str, dict[str, Any]]:
    """Configured tokens, env-only. Malformed config authenticates nobody."""
    raw = os.environ.get("ORCH_COMPLIANCE_API_TOKENS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def auth_configured() -> bool:
    return bool(_token_registry())


def token_fingerprint(token: str) -> str:
    """Short, salted, non-reversible tag so audit logs can correlate calls."""
    if not token:
        return "none"
    salt = os.environ.get("ORCH_COMPLIANCE_API_LOG_SALT", "compliance-audit")
    return hashlib.sha256((salt + token).encode("utf-8", "replace")).hexdigest()[:12]


def is_loopback(client_host: str | None) -> bool:
    return str(client_host or "").strip().lower() in LOOPBACK_HOSTS


def resolve_principal(token: str | None = None, client_host: str | None = None) -> Principal:
    """Attribute a request to a principal, or raise AuthError.

    Order matters. A presented token is always evaluated on its own merits —
    coming from loopback must never upgrade a bad token into a good one, or a
    local browser page could authenticate by guessing.
    """
    registry = _token_registry()

    if token:
        if not registry:
            raise AuthError("no authentication adapter configured", 401)
        match = None
        for candidate, spec in registry.items():
            # compare_digest on every candidate: no early return, so timing
            # does not reveal how much of a token was correct.
            if hmac.compare_digest(str(candidate), str(token)):
                match = spec
        if match is None:
            raise AuthError("invalid token", 401)
        if not isinstance(match, dict):
            raise AuthError("malformed token configuration", 401)
        scopes = match.get("scopes") or [READ]
        return Principal(
            name=str(match.get("principal") or "token"),
            tenant=str(match.get("tenant") or "default"),
            scopes=frozenset(str(s) for s in scopes),
            via="token",
        )

    if registry:
        # An adapter IS configured; anonymous access is no longer implied.
        raise AuthError("authentication required", 401)

    if is_loopback(client_host):
        return LOCAL_PRINCIPAL

    raise AuthError(
        "compliance API is loopback-only until ORCH_COMPLIANCE_API_TOKENS is configured", 403)


def authorize_tenant(principal: Principal, requested_tenant: str | None) -> str:
    """Return the tenant to act on. The principal decides, not the request.

    A request may still *name* a tenant; naming one it does not own is a 403
    rather than a silent redirect, so cross-tenant attempts are visible in the
    audit log instead of being quietly rewritten.
    """
    if requested_tenant and str(requested_tenant) != principal.tenant:
        if not principal.may(ADMIN):
            raise AuthError(
                f"principal '{principal.name}' may not act on tenant "
                f"'{requested_tenant}'", 403)
        return str(requested_tenant)
    return principal.tenant


def require_scope(principal: Principal, scope: str) -> None:
    if not principal.may(scope):
        raise AuthError(f"principal '{principal.name}' lacks '{scope}' scope", 403)


def check_body_size(size_bytes: int | None) -> None:
    try:
        size = int(size_bytes or 0)
    except (TypeError, ValueError):
        raise AuthError("unreadable Content-Length", 400)
    if size < 0:
        raise AuthError("negative Content-Length", 400)
    if size > MAX_BODY_BYTES:
        raise AuthError(f"request body exceeds {MAX_BODY_BYTES} bytes", 413)


class RateLimiter:
    """Fixed-window per-principal limiter. Thread-safe, memory-bounded."""

    def __init__(self, limit: int | None = None, window_s: int | None = None):
        self.limit = RATE_LIMIT_REQUESTS if limit is None else limit
        self.window_s = RATE_LIMIT_WINDOW_S if window_s is None else window_s
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if self.limit <= 0:
            return
        now = time.time()
        cutoff = now - self.window_s
        with self._lock:
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.limit:
                hits.append(now)
                self._hits[key] = hits[-self.limit:]
                raise AuthError(
                    f"rate limit exceeded ({self.limit} per {self.window_s}s)", 429)
            hits.append(now)
            self._hits[key] = hits
            # Drop idle keys so a stream of distinct principals cannot grow
            # this map without bound.
            if len(self._hits) > 4096:
                for stale in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
                    self._hits.pop(stale, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


def cors_headers(origin: str | None) -> dict[str, str]:
    """Echo only an explicitly allowed origin. Never `*`."""
    if origin and origin in ALLOWED_ORIGINS:
        return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
    return {"Vary": "Origin"}


def audit(action: str, principal: Principal | None, *, status: int,
          detail: str = "", **extra: Any) -> None:
    """Structured audit record. Never raises, never logs a token or a body."""
    payload = {
        "action": action, "status": status,
        "principal": principal.name if principal else "anonymous",
        "tenant": principal.tenant if principal else None,
        "via": principal.via if principal else None,
        "detail": detail[:500],
    }
    payload.update({k: v for k, v in extra.items() if k != "token"})
    try:
        import events
        events.emit("compliance:api_audit", **payload)
    except Exception:
        pass
