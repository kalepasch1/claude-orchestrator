#!/usr/bin/env python3
"""Provider trust metadata for routing policy.

The orchestrator can optimize cost only after it knows whether a provider is
allowed to see confidential work. Defaults are conservative for external APIs
and can be overridden with ORCH_PROVIDER_TERMS_JSON.
"""
import json
import os


DEFAULTS = {
    "local": {"trust": "local", "training": "none", "confidential_ok": True, "crown_jewel_ok": True},
    "ollama": {"trust": "local", "training": "none", "confidential_ok": True, "crown_jewel_ok": True},
    "claude": {"trust": "subscription", "training": "vendor_terms", "confidential_ok": False, "crown_jewel_ok": False},
    "codex": {"trust": "subscription", "training": "vendor_terms", "confidential_ok": False, "crown_jewel_ok": False},
    "openai": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "gpt": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "gpt-mini": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "google": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "gemini": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "deepseek": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "groq": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "xai": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
    "grok": {"trust": "api", "training": "configure_account", "confidential_ok": False, "crown_jewel_ok": False},
}


def _overrides():
    raw = os.environ.get("ORCH_PROVIDER_TERMS_JSON", "")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def metadata(provider):
    key = str(provider or "").lower()
    base = dict(DEFAULTS.get(key, {"trust": "unknown", "training": "unknown",
                                   "confidential_ok": False, "crown_jewel_ok": False}))
    override = _overrides().get(key) or {}
    if isinstance(override, dict):
        base.update(override)
    return base


def allowed(provider, sensitivity="standard"):
    level = str(sensitivity or "standard").lower()
    if level in ("standard", "public", "routine"):
        return True
    meta = metadata(provider)
    if level in ("crown_jewel", "crown-jewel", "crownjewel"):
        return bool(meta.get("crown_jewel_ok"))
    if level == "confidential":
        return bool(meta.get("confidential_ok") or meta.get("crown_jewel_ok"))
    return False


def filter_allowed(providers, sensitivity="standard"):
    return [p for p in providers if allowed(p, sensitivity)]


if __name__ == "__main__":
    print(json.dumps(DEFAULTS, indent=2))
