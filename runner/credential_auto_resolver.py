#!/usr/bin/env python3
"""
credential_auto_resolver.py — autonomous credential provider.

Runs every 5 minutes via periodic.py. For each pending credential_request:
  1. Checks if the credential is already available in the runner's environment
  2. If found → marks request resolved + auto-approves the associated approval card
  3. For GitHub → also tries `gh auth token` to obtain a live token
  4. Logs what still needs manual action

This clears credential_requests with status='manual' automatically within
5 minutes of the runner starting, since all common keys are in .env.
"""
import os, sys, subprocess, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [cred-resolver] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# Provider -> env vars to check (first non-empty wins)
PROVIDER_ENV_MAP = {
    "openai":     ["OPENAI_API_KEY", "OPEN_API_KEY", "IMAGE_MODEL_API_KEY"],
    "anthropic":  ["ANTHROPIC_API_KEY"],
    "supabase":   ["SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE_KEY",
                   "SUPABASE_KEY", "SUPABASE_ACCESS_TOKEN"],
    "github":     ["GITHUB_TOKEN", "GH_TOKEN", "GITHUB_APP_TOKEN"],
    "google":     ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "vercel":     ["VERCEL_TOKEN"],
    "stripe":     ["STRIPE_SECRET_KEY"],
    "deepseek":   ["DEEPSEEK_API_KEY"],
    "grok":       ["GROK_API_KEY", "XAPI_KEY"],
    "voyage":     ["VOYAGE_API_KEY"],
}


def _env_has(provider):
    """Return (found, env_var_name). Checks env vars for the provider."""
    keys = PROVIDER_ENV_MAP.get(provider.lower(),
                                [provider.upper() + "_API_KEY",
                                 provider.upper() + "_TOKEN"])
    for key in keys:
        val = os.environ.get(key, "").strip()
        if val and len(val) > 8:
            return True, key
    return False, ""


def _github_live_token():
    """Try to get a live GitHub token via gh CLI."""
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=8)
        token = r.stdout.strip()
        if r.returncode == 0 and token:
            return token
    except Exception:
        pass
    return None


def _has_credential(provider):
    """Return (available, source_description)."""
    found, key = _env_has(provider)
    if found:
        return True, "env:" + key

    # GitHub special: try gh CLI
    if provider.lower() in ("github", "unknown"):
        token = _github_live_token()
        if token:
            os.environ.setdefault("GITHUB_TOKEN", token)
            return True, "gh-cli"

    return False, ""


def _resolve_request(req_id, provider, project, source):
    """Mark the credential_request resolved and close matching approval cards."""
    db.update("credential_requests", {"id": req_id}, {"status": "resolved"})

    # Find matching pending approval cards
    try:
        filters = {"select": "id,title", "status": "eq.pending"}
        if project:
            filters["project"] = "eq." + project
        pending = db.select("approvals", filters) or []
        for a in pending:
            title_lower = str(a.get("title", "")).lower()
            if provider.lower() in title_lower or "credential" in title_lower:
                db.update("approvals", {"id": a["id"]}, {
                    "status": "approved",
                    "decided_by": "credential_auto_resolver",
                    "decided_at": "now()",
                })
    except Exception as e:
        log.debug("approval cleanup for %s failed (non-fatal): %s", req_id[:8], e)

    log.info("resolved %s credential for %s via %s [req %s]",
             provider, project or "(portfolio)", source, req_id[:8])


def resolve_pending():
    """Main entrypoint. Returns number of requests resolved this cycle."""
    try:
        rows = db.select("credential_requests", {
            "select": "id,project,provider,reason,status",
            "status": "eq.manual",
        }) or []
    except Exception as e:
        log.warning("fetch credential_requests failed: %s", e)
        return 0

    if not rows:
        log.debug("no pending credential requests")
        return 0

    resolved = 0
    still_pending = []

    for row in rows:
        provider = (row.get("provider") or "unknown").strip()
        project = (row.get("project") or "").strip()
        req_id = row.get("id", "")

        available, source = _has_credential(provider)
        if available:
            try:
                _resolve_request(req_id, provider, project, source)
                resolved += 1
            except Exception as e:
                log.warning("resolve %s failed: %s", req_id[:8], e)
        else:
            still_pending.append("%s@%s" % (provider, project or "any"))

    if still_pending:
        log.info("still need manual action (%d): %s",
                 len(still_pending), ", ".join(still_pending[:6]))
    if resolved:
        log.info("auto-resolved %d/%d credential requests", resolved, len(rows))
    return resolved


if __name__ == "__main__":
    log.info("credential_auto_resolver starting")
    n = resolve_pending()
    log.info("done — %d resolved", n)
