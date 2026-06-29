#!/usr/bin/env python3
"""
providers.py - per-provider plugins for PROGRAMMATIC key provisioning/rotation/revocation +
usage, using each provider's MANAGEMENT API (which you've authorized via a management token in
env). If a provider has no management API or needs signup/payment, the plugin returns
{"manual": True} or {"payment_required": True} so the broker prompts you instead of guessing.

NEVER hardcode a secret here. Plugins read management tokens from env and return secret REFS,
not values. Add real providers by filling in the stubs.

After rotate() succeeds, deploy_env_sync(provider, name, new_ref, project) should be called
to push the new ref to Vercel / Supabase env. rotate_keys.py does this automatically.
"""
import os, json
try:
    import urllib.request as _urllib
except ImportError:
    _urllib = None

def _has(env): return bool(os.environ.get(env))
def _env(env): return os.environ.get(env, "")


def _generic_manual(provider):
    return {"manual": True,
            "note": f"{provider} has no management API configured; provision/rotate in its dashboard."}


def _vercel_request(path, method="GET", body=None):
    """Make a Vercel REST API call. Needs VERCEL_TOKEN in env."""
    token = _env("VERCEL_TOKEN")
    if not token:
        return None, "VERCEL_TOKEN not set"
    url = f"https://api.vercel.com{path}"
    data = json.dumps(body).encode() if body else None
    req = _urllib.Request(url, data=data, method=method,
                         headers={"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"})
    try:
        with _urllib.urlopen(req, timeout=15) as r:
            return json.loads(r.read()), None
    except Exception as e:
        return None, str(e)


# ── OpenAI ────────────────────────────────────────────────────────────────────

def openai_provision(project):
    """
    Create a project API key via OpenAI's admin/management API.
    Needs OPENAI_ADMIN_KEY (a top-level org admin key, not a project key).
    """
    admin_key = _env("OPENAI_ADMIN_KEY")
    if not admin_key:
        return {"manual": True,
                "note": "Set OPENAI_ADMIN_KEY (org admin key) to auto-provision OpenAI project keys. "
                        "Otherwise create manually at platform.openai.com → API keys."}
    # OpenAI Management API: POST /v1/organization/projects (beta)
    # https://platform.openai.com/docs/api-reference/projects
    try:
        req = _urllib.Request(
            "https://api.openai.com/v1/organization/projects",
            data=json.dumps({"name": project or "orchestrator"}).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"})
        with _urllib.urlopen(req, timeout=15) as r:
            proj_data = json.loads(r.read())
        proj_id = proj_data.get("id")
        if not proj_id:
            return {"manual": True, "note": f"OpenAI project create returned: {proj_data}"}
        # Create an API key for this project
        req2 = _urllib.Request(
            f"https://api.openai.com/v1/organization/projects/{proj_id}/api_keys",
            data=json.dumps({"name": f"orchestrator-{project or 'default'}"}).encode(),
            method="POST",
            headers={"Authorization": f"Bearer {admin_key}", "Content-Type": "application/json"})
        with _urllib.urlopen(req2, timeout=15) as r2:
            key_data = json.loads(r2.read())
        value = key_data.get("value")
        if not value:
            return {"manual": True, "note": f"OpenAI key create returned: {key_data}"}
        # Store the value in the env so secrets_manager can pick it up via ref=env:OPENAI_API_KEY_<proj>
        env_ref = f"OPENAI_API_KEY_{(project or 'default').upper().replace('-', '_')}"
        os.environ[env_ref] = value
        return {"ref": env_ref, "store": "env",
                "note": f"Provisioned OpenAI key for project {proj_id}; stored in env:{env_ref}"}
    except Exception as e:
        return {"manual": True, "note": f"OpenAI admin API error: {e}"}


def openai_rotate(project):
    """Rotate = provision new key (OpenAI doesn't support rotate-in-place; old key must be revoked manually)."""
    result = openai_provision(project)
    if result.get("ref"):
        result["note"] = (result.get("note", "") +
                          " — revoke the OLD key at platform.openai.com/api-keys once the new one is wired.")
    return result


# ── Supabase ──────────────────────────────────────────────────────────────────

def supabase_rotate(project):
    """
    Rotate Supabase service-role key via the Supabase Management API.
    Needs SUPABASE_ACCESS_TOKEN (personal access token from supabase.com/dashboard/account/tokens)
    and SUPABASE_PROJECT_REF (the project ref, e.g. 'abcdefghijklmnop').
    """
    access_token = _env("SUPABASE_ACCESS_TOKEN")
    proj_ref = _env("SUPABASE_PROJECT_REF")
    if not access_token or not proj_ref:
        return {"manual": True,
                "note": "Set SUPABASE_ACCESS_TOKEN + SUPABASE_PROJECT_REF to auto-rotate. "
                        "Otherwise rotate in Project Settings → API (Supabase dashboard)."}
    try:
        req = _urllib.Request(
            f"https://api.supabase.com/v1/projects/{proj_ref}/secrets/rotate",
            data=b"{}",
            method="POST",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
        with _urllib.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read())
        new_key = resp.get("service_role_key") or resp.get("anon_key")
        if new_key:
            env_ref = "SUPABASE_SERVICE_KEY"
            os.environ[env_ref] = new_key
            return {"ref": env_ref, "store": "env",
                    "note": f"Supabase service-role key rotated; stored in env:{env_ref}"}
        return {"manual": True, "note": f"Supabase rotate returned: {resp}"}
    except Exception as e:
        return {"manual": True, "note": f"Supabase management API error: {e}"}


# ── Vercel ────────────────────────────────────────────────────────────────────

def vercel_rotate(project):
    """
    Vercel doesn't have a 'service key' to rotate, but we can update an env var on a project.
    Returns {"manual": True} — env var updates are done via deploy_env_sync().
    """
    if not _has("VERCEL_TOKEN"):
        return {"manual": True,
                "note": "Set VERCEL_TOKEN to enable Vercel env updates. "
                        "Rotate secrets via vercel env rm / vercel env add in the dashboard."}
    return {"manual": True,
            "note": "Vercel uses deploy env vars, not rotating API keys. "
                    "Use deploy_env_sync() to push a new ref to Vercel env after rotation."}


def vercel_deploy_env_sync(project, env_key, env_value, env_type="encrypted"):
    """
    Update a Vercel environment variable for a project.
    Needs VERCEL_TOKEN and VERCEL_PROJECT_ID (or VERCEL_PROJECT_<UPPER_PROJECT>).
    env_type: 'encrypted' (secret) | 'plain' | 'system'
    """
    token = _env("VERCEL_TOKEN")
    project_id = _env(f"VERCEL_PROJECT_ID_{project.upper().replace('-', '_')}") or _env("VERCEL_PROJECT_ID")
    if not token or not project_id:
        return False, "VERCEL_TOKEN and VERCEL_PROJECT_ID required for env sync"
    # List existing env vars to find the one to update
    existing, err = _vercel_request(f"/v9/projects/{project_id}/env")
    if err:
        return False, f"Vercel list env: {err}"
    envs = existing.get("envs", []) if existing else []
    existing_id = next((e["id"] for e in envs if e.get("key") == env_key), None)
    body = {"key": env_key, "value": env_value, "type": env_type, "target": ["production", "preview", "development"]}
    if existing_id:
        resp, err = _vercel_request(f"/v9/projects/{project_id}/env/{existing_id}", method="PATCH", body=body)
    else:
        resp, err = _vercel_request(f"/v9/projects/{project_id}/env", method="POST", body=body)
    if err:
        return False, f"Vercel env update: {err}"
    return True, "Vercel env updated"


# ── Stripe ────────────────────────────────────────────────────────────────────

def stripe_provision(project):
    """Stripe live keys require billing setup and must be done in the Stripe dashboard."""
    return {"payment_required": True,
            "note": "Stripe live keys require an active account with billing. "
                    "Create at dashboard.stripe.com → Developers → API keys."}


REGISTRY = {
    "openai":    {"provision": openai_provision, "rotate": openai_rotate},
    "anthropic": {"provision": lambda p: {
                  "payment_required": True,
                  "note": "Anthropic API billing is pay-as-you-go; activating/raising limits needs your payment."}},
    "supabase":  {"rotate": supabase_rotate},
    "vercel":    {"rotate": vercel_rotate, "deploy_env_sync": vercel_deploy_env_sync},
    "stripe":    {"provision": stripe_provision},
}


def call(provider, action, *args):
    plugin = REGISTRY.get(provider, {})
    fn = plugin.get(action)
    if not fn:
        return _generic_manual(provider)
    try:
        return fn(*args)
    except Exception as e:
        return {"manual": True, "note": f"{provider}.{action} failed: {e}"}


def deploy_env_sync(provider, env_key, env_value, project=None):
    """
    Push a new env var value to all configured deploy targets (Vercel + Supabase env).
    Called by rotate_keys after a successful rotation.
    Returns list of (target, success, note) tuples.
    """
    results = []
    # Vercel
    if _has("VERCEL_TOKEN") and _has("VERCEL_PROJECT_ID"):
        ok, note = vercel_deploy_env_sync(project or "default", env_key, env_value)
        results.append(("vercel", ok, note))
    # Supabase env secrets (via management API)
    if _has("SUPABASE_ACCESS_TOKEN") and _has("SUPABASE_PROJECT_REF"):
        proj_ref = _env("SUPABASE_PROJECT_REF")
        access_token = _env("SUPABASE_ACCESS_TOKEN")
        try:
            body = json.dumps([{"name": env_key, "value": env_value}]).encode()
            req = _urllib.Request(
                f"https://api.supabase.com/v1/projects/{proj_ref}/secrets",
                data=body, method="POST",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
            with _urllib.urlopen(req, timeout=15) as r:
                r.read()
            results.append(("supabase_env", True, f"env var {env_key} pushed to Supabase"))
        except Exception as e:
            results.append(("supabase_env", False, str(e)))
    if not results:
        results.append(("none", False, "No deploy targets configured (set VERCEL_TOKEN or SUPABASE_ACCESS_TOKEN)"))
    return results
