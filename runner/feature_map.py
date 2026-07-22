"""
Cross-app critical feature map.

Machine-readable config capturing critical surfaces across the portfolio:
Tomorrow, Apparently, Smarter, Hisanta, Galop, Pareto/2080, and the orchestrator.

Each surface records: owner_app, reusable_capabilities, proof_command,
privacy_tier, and propagation_eligible.
"""

from __future__ import annotations


import json
import os
from typing import Any, Optional

# ── Known apps ──────────────────────────────────────────────────────
KNOWN_APPS = frozenset([
    "tomorrow",
    "apparently",
    "smarter",
    "hisanta",
    "galop",
    "pareto",
    "orchestrator",
])
# ── Privacy tiers (ascending sensitivity) ───────────────────────────
PRIVACY_TIERS = ("public", "internal", "confidential", "restricted")

# ── Surface schema keys ────────────────────────────────────────────
REQUIRED_SURFACE_KEYS = frozenset([
    "owner_app",
    "reusable_capabilities",
    "proof_command",
    "privacy_tier",
    "propagation_eligible",
])

# ── The canonical feature map ──────────────────────────────────────
FEATURE_MAP: dict[str, dict[str, Any]] = {
    "deliberation_cade": {
        "owner_app": "orchestrator",
        "reusable_capabilities": ["debate_compress", "decision_engine", "cade_scorecard"],
        "proof_command": "python3 -m pytest runner/tests/test_cade_scorecard.py -q",
        "privacy_tier": "confidential",
        "propagation_eligible": True,
    },
    "negotiation_rooms": {
        "owner_app": "tomorrow",
        "reusable_capabilities": ["presettlement_sim", "live_bidding", "decision_drafts"],
        "proof_command": "python3 -m pytest runner/tests/test_decision_drafts.py -q",
        "privacy_tier": "restricted",
        "propagation_eligible": False,
    },
    "app_optimization_loops": {
        "owner_app": "orchestrator",
        "reusable_capabilities": ["meta_loop", "self_tune", "auto_experiment"],
        "proof_command": "python3 -m pytest runner/tests -q -k 'meta or tune'",
        "privacy_tier": "internal",
        "propagation_eligible": True,
    },
    "contract_generation": {
        "owner_app": "tomorrow",
        "reusable_capabilities": ["spec_writer", "prompt_factory", "legal_filter"],
        "proof_command": "python3 -m pytest runner/tests/test_prompt_factory.py -q",
        "privacy_tier": "restricted",
        "propagation_eligible": False,
    },
    "ioi_relationships_matching": {
        "owner_app": "apparently",
        "reusable_capabilities": ["scoring", "semantic_dedupe", "context_retrieval"],
        "proof_command": "python3 -m pytest runner/tests/test_semantic_dedupe.py -q",
        "privacy_tier": "restricted",
        "propagation_eligible": False,
    },
    "licensing_registration_intake": {
        "owner_app": "apparently",
        "reusable_capabilities": ["legal_triage", "legal_prebrief", "intake_compiler"],
        "proof_command": "python3 -m pytest runner/tests/test_intake_compiler.py -q",
        "privacy_tier": "restricted",
        "propagation_eligible": False,
    },
    "owner_controller_employee_data": {
        "owner_app": "apparently",
        "reusable_capabilities": ["privacy", "rls_guard", "credential_broker"],
        "proof_command": "python3 -m pytest runner/tests/test_safety.py -q",
        "privacy_tier": "restricted",
        "propagation_eligible": False,
    },
    "memo_rlo_review": {
        "owner_app": "tomorrow",
        "reusable_capabilities": ["self_review", "approval_policy", "judge"],
        "proof_command": "python3 -m pytest runner/tests/test_approval_policy.py -q",
        "privacy_tier": "confidential",
        "propagation_eligible": True,
    },
    "project_coordination": {
        "owner_app": "orchestrator",
        "reusable_capabilities": ["planner", "dag_optimizer", "wave_pipeline"],
        "proof_command": "python3 -m pytest runner/tests/test_pipeline_contract.py -q",
        "privacy_tier": "internal",
        "propagation_eligible": True,
    },
    "email_ingestion_sorting": {
        "owner_app": "galop",
        "reusable_capabilities": ["intake_watcher", "intake_dedup", "intent_compiler"],
        "proof_command": "python3 -m pytest runner/tests/test_intake_dedup.py -q",
        "privacy_tier": "confidential",
        "propagation_eligible": True,
    },
    "temperament_collaboration_scoring": {
        "owner_app": "smarter",
        "reusable_capabilities": ["scoring", "confidence", "pattern_compiler"],
        "proof_command": "python3 -m pytest runner/tests/test_pattern_compiler.py -q",
        "privacy_tier": "confidential",
        "propagation_eligible": True,
    },
    "cybersecurity": {
        "owner_app": "orchestrator",
        "reusable_capabilities": ["kill_switch", "sentinel", "rls_guard"],
        "proof_command": "python3 -m pytest runner/tests/test_kill_switch.py -q",
        "privacy_tier": "restricted",
        "propagation_eligible": False,
    },
    "design_ui_ux": {
        "owner_app": "hisanta",
        "reusable_capabilities": ["preview_deployer", "preview_canary", "preview_promote"],
        "proof_command": "python3 -m pytest runner/tests/test_preview_promote_flow.py -q",
        "privacy_tier": "internal",
        "propagation_eligible": True,
    },
    "deployment_health": {
        "owner_app": "orchestrator",
        "reusable_capabilities": ["deploy_verify", "deploy_watch", "canary"],
        "proof_command": "python3 -m pytest runner/tests/test_deploy_watch_escalation.py -q",
        "privacy_tier": "internal",
        "propagation_eligible": True,
    },
    "shared_proof_packs": {
        "owner_app": "pareto",
        "reusable_capabilities": ["proof_propagation", "session_proof", "provenance"],
        "proof_command": "python3 -m pytest runner/tests/test_session_proof.py -q",
        "privacy_tier": "confidential",
        "propagation_eligible": True,
    },
}


def get_feature_map() -> dict[str, dict[str, Any]]:
    """Return the full feature map (deep copy)."""
    import copy
    return copy.deepcopy(FEATURE_MAP)


def get_surface(name: str) -> dict[str, Any] | None:
    """Return a single surface config, or None if not found."""
    import copy
    surface = FEATURE_MAP.get(name)
    return copy.deepcopy(surface) if surface else None


def surfaces_for_app(app: str) -> dict[str, dict[str, Any]]:
    """Return all surfaces owned by *app*.

    Unknown apps return an empty dict (fail-soft).
    """
    import copy
    return {
        name: copy.deepcopy(cfg)
        for name, cfg in FEATURE_MAP.items()
        if cfg["owner_app"] == app
    }

def validate_map(fmap: dict[str, dict[str, Any]] | None = None) -> list[str]:
    """Return a list of validation errors (empty == valid)."""
    fmap = fmap or FEATURE_MAP
    errors: list[str] = []
    for name, cfg in fmap.items():
        missing = REQUIRED_SURFACE_KEYS - set(cfg.keys())
        if missing:
            errors.append(f"{name}: missing keys {sorted(missing)}")
        if cfg.get("privacy_tier") not in PRIVACY_TIERS:
            errors.append(f"{name}: invalid privacy_tier '{cfg.get('privacy_tier')}'")
        if cfg.get("owner_app") not in KNOWN_APPS:
            errors.append(f"{name}: unknown owner_app '{cfg.get('owner_app')}'")
    return errors


def apps_covered(fmap: dict[str, dict[str, Any]] | None = None) -> set[str]:
    """Return the set of apps that own at least one surface."""
    fmap = fmap or FEATURE_MAP
    return {cfg["owner_app"] for cfg in fmap.values() if "owner_app" in cfg}


def export_json(path: Optional[str] = None) -> str:
    """Export the feature map as JSON. If *path* given, also write to file."""
    data = json.dumps(FEATURE_MAP, indent=2, sort_keys=True)
    if path:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(data)
    return data
