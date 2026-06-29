#!/usr/bin/env python3
"""
rotate_keys.py - rotate a provider key fast from the orchestration layer (security). For
providers with a management API it creates a new key, registers the new ref, marks the old
revoked, and syncs the new value to all live deploy envs (Vercel + Supabase). Otherwise it
files a guided rotation card. Triggered by the dashboard "Rotate" button (a queued control
task) or run directly.

revoke_all(provider): security panic — immediately revokes all active keys for a provider.
"""
import os, sys, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, providers, secrets_manager


def rotate(provider, name, project=None):
    res = providers.call(provider, "rotate", project)
    if res.get("ref") or res.get("value_env"):
        new_ref = res.get("ref") or res["value_env"]
        # mark old revoked
        for r in db.select("secrets", {"select": "id", "provider": f"eq.{provider}",
                                       "name": f"eq.{name}", "status": "eq.active"}) or []:
            db.update("secrets", {"id": r["id"]}, {"status": "revoked"})
        secrets_manager.register(provider, name, new_ref,
                                 store=res.get("store", "env"), project=project)
        db.update("secrets", {"provider": provider, "name": name, "status": "active"},
                  {"last_rotated": datetime.datetime.utcnow().isoformat()})
        # deploy env sync: push the live value to Vercel / Supabase env
        sync_note = ""
        try:
            # Resolve the actual value via secrets_manager (never log it)
            new_value = secrets_manager._read(res.get("store", "env"), new_ref)
            if new_value:
                sync_results = providers.deploy_env_sync(provider, name, new_value, project)
                sync_note = "; ".join(f"{t}:{'ok' if ok else 'FAIL: '+n}" for t, ok, n in sync_results)
            else:
                sync_note = "deploy env sync skipped (value not resolvable — update manually)"
        except Exception as e:
            sync_note = f"deploy env sync error: {e}"
        note = f"rotated; deploy sync: {sync_note}"
        return {"ok": True, "note": note}
    db.insert("approvals", {"project": project or "PORTFOLIO", "kind": "self",
              "title": f"Rotate {provider} key manually",
              "why": res.get("note", "no management API configured"),
              "value": "Security rotation.", "risk": "Old key stays valid until you revoke it.",
              "command": ""})
    return {"ok": False, "manual": True, "note": res.get("note")}


def revoke_all(provider, project=None, reason="security panic"):
    """
    Immediately revoke all active secrets for a provider. Used by the panic button.
    Marks all active rows revoked, attempts provider-level revocation, and files an approval card.
    """
    rows = db.select("secrets", {"select": "*", "provider": f"eq.{provider}",
                                 "status": "eq.active"}) or []
    if project:
        rows = [r for r in rows if r.get("project") in (project, None)]
    revoked = 0
    for r in rows:
        db.update("secrets", {"id": r["id"]}, {"status": "revoked",
                 "last_rotated": datetime.datetime.utcnow().isoformat()})
        # best-effort provider revocation
        try:
            providers.call(provider, "revoke", r.get("ref"))
        except Exception:
            pass
        revoked += 1
    db.insert("approvals", {"project": project or "PORTFOLIO", "kind": "material",
              "title": f"SECURITY: {revoked} {provider} key(s) revoked ({reason})",
              "why": reason, "value": "Breach containment.",
              "risk": "All {provider} API calls will fail until new keys are provisioned.",
              "command": f"python3 rotate_keys.py {provider} {provider.upper()}_API_KEY"})
    return {"revoked": revoked, "provider": provider}


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        print(rotate(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None))
    elif len(sys.argv) == 2 and sys.argv[1].startswith("revoke:"):
        prov = sys.argv[1].split(":", 1)[1]
        print(revoke_all(prov))
    else:
        print("usage: rotate_keys.py <provider> <name> [project]")
        print("       rotate_keys.py revoke:<provider>   # security panic")
