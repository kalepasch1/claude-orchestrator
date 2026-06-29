#!/usr/bin/env python3
"""
credential_broker.py - keeps sessions unblocked on credentials WITHOUT bugging you, and only
prompts when PAYMENT or a manual signup is genuinely required.

needs(provider, name, project, reason):
  1) already in the secret store?  -> done, inject it.
  2) provider has a management API? -> provision programmatically, register the ref.
  3) needs payment or manual signup -> file a credential_request + an approval card (the ONLY
     time you're prompted), with payment_required flagged clearly.
detect_from_output(out, project): infer an auth failure from an agent's run log and trigger needs().
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, secrets_manager, providers

AUTH_SIGNALS = re.compile(r"(invalid api key|missing api key|no api key|unauthorized|401|403|"
                          r"authentication failed|api key not found|set .*_API_KEY)", re.I)
PROVIDER_HINTS = {"openai": "openai", "anthropic": "anthropic", "supabase": "supabase",
                  "vercel": "vercel", "stripe": "stripe", "github": "github"}


def needs(provider, name, project, reason=""):
    if secrets_manager.resolve(provider, name, project):
        return {"ok": True, "source": "store"}
    res = providers.call(provider, "provision", project)
    if res.get("ref") or res.get("value_env"):
        secrets_manager.register(provider, name, res.get("ref") or res["value_env"],
                                 store=res.get("store", "env"), project=project)
        return {"ok": True, "source": "provisioned"}
    status = "payment_required" if res.get("payment_required") else "manual"
    db.insert("credential_requests", {"project": project, "provider": provider,
                                      "reason": reason or res.get("note", ""), "status": status})
    db.insert("approvals", {"project": project or "PORTFOLIO",
              "kind": "material" if status == "payment_required" else "self",
              "title": f"{'💳 Payment required' if status=='payment_required' else 'Credential needed'}: {provider}",
              "why": reason or res.get("note", ""),
              "value": f"Unblocks {project or 'the swarm'} once {provider} is set up.",
              "risk": "Requires your action (" + ("payment" if status == "payment_required" else "signup/manual key") + ").",
              "command": ""})
    return {"ok": False, "status": status, "note": res.get("note")}


def detect_from_output(out, project):
    if not out or not AUTH_SIGNALS.search(out):
        return None
    low = out.lower()
    provider = next((p for hint, p in PROVIDER_HINTS.items() if hint in low), "unknown")
    name = f"{provider.upper()}_API_KEY"
    return needs(provider, name, project, reason="agent hit an auth failure")


if __name__ == "__main__":
    print("credential_broker: resolves/provisions creds; only prompts on payment/manual.")
