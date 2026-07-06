#!/usr/bin/env python3
"""
subscription_guard.py - the billing firewall that keeps fixed-price subscriptions first and makes
paid Anthropic API billing an explicit fallback instead of an accidental default.

Where that money went (all bypass the Max plan and bill the API):
  * batch_pass.py  -> Claude Batch API via a raw ANTHROPIC_API_KEY (scheduled twice daily).
  * account_pool   -> any type="api" account injects ANTHROPIC_API_KEY.
  * a stray key in the environment -> Claude Code bills API instead of the subscription.
  * auto-recharge on the account silently re-bought credits so it never hard-stopped.

enforce() (call ONCE at runner startup, before anything else):
  Unless ORCH_ALLOW_API_BILLING=true, it REMOVES ANTHROPIC_API_KEY and every ANTHROPIC_API_KEY_*
  from this process's environment. Because the runner launches all periodic jobs as subprocesses with
  a COPY of its environment, the key is gone everywhere - batch_pass, edge calls, and api-accounts all
  lose the ability to bill. Subscription (Max) usage is unaffected (it uses the logged-in CLI session).

audit() returns what it stripped so startup can log it. is_api_allowed() is the single switch other
modules check before doing anything that would bill the API. Subscription mode controls route
priority; ORCH_ALLOW_API_BILLING=true is the explicit permission for paid fallback.

NOTE: the strongest control is on the ACCOUNT itself and only you can set it - turn OFF auto-recharge
and set a $0/low monthly spend limit in the Anthropic Console. This module guarantees the ORCHESTRATOR
never bills the API; the console setting guarantees NOTHING can, even outside this tool.
"""
import os

SUB_ON = os.environ.get("ORCH_USE_SUBSCRIPTION", "true").lower() == "true"
# explicit, deliberate opt-in required to ever touch API billing (default: never)
API_OPT_IN = os.environ.get("ORCH_ALLOW_API_BILLING", "false").lower() == "true"


def is_api_allowed():
    """API billing is allowed only when explicitly opted in.

    Subscription mode controls priority (fixed-price first), not an absolute ban once the owner has
    enabled paid fallback with ORCH_ALLOW_API_BILLING=true.
    """
    return API_OPT_IN


def _api_key_vars():
    return [k for k in list(os.environ.keys())
            if k == "ANTHROPIC_API_KEY" or k.startswith("ANTHROPIC_API_KEY_")]


def enforce():
    """Strip every Anthropic API key from the process env unless API billing is explicitly allowed.
    Returns a dict describing what was done (for logging)."""
    if is_api_allowed():
        return {"enforced": False, "reason": "API billing explicitly opted in (subscription-first fallback mode)",
                "stripped": []}
    stripped = []
    for k in _api_key_vars():
        os.environ.pop(k, None)
        stripped.append(k)
    # also neutralize the auto-recharge-style env hints if any tooling reads them
    os.environ["ORCH_API_BILLING_BLOCKED"] = "1"
    return {"enforced": True, "subscription_mode": SUB_ON, "stripped": stripped}


def audit():
    """Report residual API-billing exposure (should be clean after enforce())."""
    return {"subscription_mode": SUB_ON, "api_opt_in": API_OPT_IN,
            "api_keys_present": _api_key_vars(),
            "api_allowed": is_api_allowed(),
            "billing_blocked_flag": os.environ.get("ORCH_API_BILLING_BLOCKED") == "1"}


def require_api_or_skip(job_name="job"):
    """Helper for any module that would bill the API (batch_pass, api-accounts). Returns True if the
    caller may proceed; otherwise logs why and returns False."""
    if is_api_allowed():
        return True
    print(f"subscription_guard: {job_name} SKIPPED - API billing is blocked in subscription-first mode. "
          f"Set ORCH_ALLOW_API_BILLING=true only if you truly intend to pay API rates.")
    return False


if __name__ == "__main__":
    import json
    print("before:", json.dumps(audit()))
    print("enforce:", json.dumps(enforce()))
    print("after:", json.dumps(audit()))
