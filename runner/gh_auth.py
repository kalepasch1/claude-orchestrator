#!/usr/bin/env python3
"""GitHub App installation-token minting with PAT and gh-CLI fallback.

Token precedence:
  1. GitHub App JWT → installation token (cached until ~expiry)
  2. GITHUB_TOKEN / GITHUB_PAT environment variable
  3. `gh auth token` CLI fallback

Env vars consumed:
  GITHUB_APP_ID              – App ID (e.g. 4261537)
  GITHUB_APP_PRIVATE_KEY_PATH – PEM file path (e.g. ~/.claude-orchestrator/github-app-*.pem)
  GITHUB_APP_INSTALLATION_ID – Installation ID (e.g. 145579394)
  GITHUB_TOKEN / GITHUB_PAT  – Personal access token fallback
"""
import json
import os
import subprocess
import threading
import time

_lock = threading.Lock()
_cached_token = None  # (token_str, expires_at_epoch)

# --- JWT helpers (pure-Python RS256, no PyJWT dependency) ---

def _b64url(data: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _mint_jwt(app_id: str, pem_path: str) -> str:
    """Create a short-lived JWT (10 min) signed with the App's private key."""
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        raise RuntimeError("cryptography package required for GitHub App auth; pip install cryptography")

    pem_path = os.path.expanduser(pem_path)
    with open(pem_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)

    now = int(time.time())
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({
        "iat": now - 60,
        "exp": now + (10 * 60),
        "iss": str(app_id),
    }).encode())
    signing_input = f"{header}.{payload}".encode("ascii")
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64url(signature)}"


def _request_installation_token(jwt: str, installation_id: str) -> dict:
    """POST to GitHub API to mint an installation access token."""
    import urllib.request
    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    req = urllib.request.Request(url, data=b"", method="POST", headers={
        "Authorization": f"Bearer {jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


# --- Public API ---

def _try_app_token() -> str | None:
    """Attempt GitHub App token mint. Returns token string or None."""
    global _cached_token
    app_id = os.environ.get("GITHUB_APP_ID", "")
    pem_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH", "")
    inst_id = os.environ.get("GITHUB_APP_INSTALLATION_ID", "")

    if not (app_id and pem_path and inst_id):
        return None

    pem_expanded = os.path.expanduser(pem_path)
    if not os.path.isfile(pem_expanded):
        return None

    with _lock:
        if _cached_token:
            token, expires = _cached_token
            if time.time() < expires - 120:  # 2-min safety margin
                return token

    try:
        jwt = _mint_jwt(app_id, pem_path)
        data = _request_installation_token(jwt, inst_id)
        token = data.get("token", "")
        # GitHub tokens expire in 1 hour; parse or default to 55 min
        expires_at = time.time() + 55 * 60
        if "expires_at" in data:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
                expires_at = dt.timestamp()
            except Exception:
                pass
        with _lock:
            _cached_token = (token, expires_at)
        return token
    except Exception:
        return None


def _try_pat_token() -> str | None:
    """Check GITHUB_TOKEN or GITHUB_PAT env vars."""
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_PAT") or None


def _try_gh_cli() -> str | None:
    """Fall back to `gh auth token`."""
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        token = r.stdout.strip()
        return token if r.returncode == 0 and token else None
    except Exception:
        return None


def gh_token() -> str:
    """Return a usable GitHub token using the App → PAT → gh CLI fallback chain.

    Returns empty string if all methods fail (fail-soft).
    """
    for method in (_try_app_token, _try_pat_token, _try_gh_cli):
        token = method()
        if token:
            return token
    return ""


def invalidate_cache():
    """Clear the cached App installation token (e.g. after a 401)."""
    global _cached_token
    with _lock:
        _cached_token = None


def has_merge_queue(repo: str) -> bool:
    """Detect if a repo has GitHub merge queue enabled (best-effort).

    Checks the repo's branch protection for the default branch via the API.
    Returns False on any error (fail-soft).
    """
    token = gh_token()
    if not token or not repo:
        return False
    # repo should be "owner/name"
    if "/" not in repo:
        return False
    try:
        import urllib.request
        # Get default branch
        url = f"https://api.github.com/repos/{repo}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        default_branch = data.get("default_branch", "main")
        # Check branch protection for merge queue
        url = f"https://api.github.com/repos/{repo}/branches/{default_branch}/protection"
        req = urllib.request.Request(url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            prot = json.loads(resp.read())
        # required_status_checks with merge_queue or merge_group context
        return bool(prot.get("required_linear_history", {}).get("enabled")) or \
               "merge_queue" in json.dumps(prot).lower()
    except Exception:
        return False


def stats() -> dict:
    """Return current auth state for diagnostics."""
    with _lock:
        cached = bool(_cached_token and time.time() < _cached_token[1] - 120)
    return {
        "app_configured": bool(os.environ.get("GITHUB_APP_ID") and
                               os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")),
        "pat_configured": bool(os.environ.get("GITHUB_TOKEN") or
                               os.environ.get("GITHUB_PAT")),
        "cached_token": cached,
    }


if __name__ == "__main__":
    print(json.dumps(stats(), indent=2))
    t = gh_token()
    print(f"gh_token() returned {'<token>' if t else '<empty>'} ({len(t)} chars)")
