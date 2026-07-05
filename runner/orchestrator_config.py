#!/usr/bin/env python3
"""
orchestrator_config.py - Runtime configuration for the orchestrator. Gating policies control
which diffs skip expensive LLM verification, and configuration can be overridden via environment.
"""
import os
import json


def load_gating_policy():
    """Load gating policy from env var or return defaults. Env format: JSON dict or comma-separated flags."""
    env_val = os.environ.get("ORCH_GATING_POLICY", "")
    if not env_val:
        # Conservative default: skip LLM verify for low-risk diffs only when tests + build pass
        return {
            "skip_llm_verify": True,
            "material_threshold": "high",  # skip verify for low/medium blast radius only
            "allow_skip_for_constitution_touch": False,  # always verify if constitution files touched
        }
    # Parse env override (e.g. "skip_llm_verify=false" or "strict" for all-verify)
    if env_val.lower() == "strict":
        return {"skip_llm_verify": False, "material_threshold": "critical", "allow_skip_for_constitution_touch": False}
    # Try JSON parsing
    try:
        return json.loads(env_val)
    except json.JSONDecodeError:
        # Fallback to comma-separated key=value
        policy = {}
        for pair in env_val.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                policy[k.strip()] = v.strip().lower() == "true"
        return policy if policy else load_gating_policy()  # fallback if parse fails


GATING_POLICY = load_gating_policy()
