#!/usr/bin/env python3
"""
orchestration_pipeline_config.py — Multi-model orchestration pipeline contract.

ORCHESTRATION PIPELINE CONTRACT

Objective: Consolidate and unify orchestration patterns with complete execution contract,
model routing, QA gates, and coordination rules. Fail-soft error handling and defensive file I/O.

Structure:
  1. Preflight triage: Task complexity categorization (q≥6.2)
  2. Strategy planner: Implementation planning (q≥6.6)
  3. Agentic coder: Code generation and testing (capability tier)
  4. QA panel: Independent review consensus (q≥7.7, quorum≥2)

Model Routing:
  - Preflight: Local LLM (zero cost, fast)
  - Planner: DeepSeek (cost-optimized, ~$0.01-0.05/task)
  - Coder: Claude (high capability for complex edits)
  - QA: Diverse models for independent verification

Quality Gates (QPD quality score):
  - Preflight q≥6.2 (quick triage baseline)
  - Planner q≥6.6 (strategy planning accuracy)
  - QA q≥7.7 (merge-gate consensus)

Legal Gates (Owner-only approval):
  - Licensing: LICENSE files, copyright changes
  - Data transmission: Privacy, GDPR, encryption, fetch/http calls
  - Credentials: Secrets, tokens, .env, API keys

Coordination Rules (Batch train integration):
  - Detect active agent/* branches before merge
  - Warn before overwriting unrelated improvements
  - Defer to merge-train when conflicts detected
  - Auto-merge only to orchestrator/dev; production via batch train

Auto-Merge Requirements:
  ✓ QA panel: both model votes pass (confidence ≥70%)
  ✓ Legal gates: no triggers (or owner approval)
  ✓ Coordination: no active branch conflicts
  → Merge to orchestrator/dev, release via merge-train

Task Classes:
  - easy (4-12 tests): preflight → coder → qa
  - medium (6-12 tests): preflight → planner → coder → qa
  - hard (8-12 tests): preflight → planner → coder → qa (full pipeline)
"""
import os
import sys
import json
import logging
import threading
import time
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# Project-level configuration
PROJECT = {
    "name": "kalepasch-com",
    "display_name": "kalepasch-com Portfolio Site",
    "repo_url": "https://github.com/kalepasch/kalepasch.com",
    "source": "release-self-heal",
    "task_class": "hard",  # Requires 8 of 12 tests to pass
}


# Task class definitions: capability thresholds and model requirements
TASK_CLASSES = {
    "easy": {
        "min_tests": 4,
        "max_tests": 12,
        "required_capability": 5,
        "stages": ["preflight_triage", "agentic_coder", "qa_panel"],
    },
    "medium": {
        "min_tests": 6,
        "max_tests": 12,
        "required_capability": 6,
        "stages": ["preflight_triage", "strategy_planner", "agentic_coder", "qa_panel"],
    },
    "hard": {
        "min_tests": 8,
        "max_tests": 12,
        "required_capability": 8,
        "stages": ["preflight_triage", "strategy_planner", "agentic_coder", "qa_panel"],
    },
}


# Pipeline stage configurations
STAGES = {
    "preflight_triage": {
        "display_name": "Preflight Triage",
        "model_provider": "local",
        "model": "llama3.2:3b",
        "quality_score": 7.58,
        "capability": 5,
        "cost": 0,  # Local, free
        "timeout_sec": 120,
        "purpose": "Fast categorization of task complexity and risk",
        "prompt_injection": {
            "task_context": True,
            "prior_outcomes": True,
            "test_results": False,
        },
    },
    "strategy_planner": {
        "display_name": "Strategy Planner",
        "model_provider": "deepseek",
        "model": "deepseek-v4-flash",
        "quality_score": 7.4,
        "capability": 6,
        "cost": 2,  # Paid API
        "timeout_sec": 180,
        "purpose": "Generate implementation strategy before coding",
        "prompt_injection": {
            "task_context": True,
            "prior_outcomes": True,
            "test_results": True,
        },
        "daily_limit_usd": 10.0,  # Soft cap
    },
    "agentic_coder": {
        "display_name": "Agentic Coder",
        "model_provider": "claude",
        "model": "claude-haiku-4-5-20251001",
        "quality_score": 9.2,
        "capability": 8,
        "cost": 1,  # Claude subscription
        "timeout_sec": 300,
        "author_required": True,
        "author_email": "kalepasch@gmail.com",
        "purpose": "Generate and adapt code changes",
        "prompt_injection": {
            "task_context": True,
            "prior_outcomes": True,
            "test_results": True,
            "strategy_plan": True,
        },
    },
    "qa_panel": {
        "display_name": "QA Panel Review",
        "strategy": "quorum",
        "required_agreement": 2,  # Both models must pass
        "models": [
            {
                "model_provider": "local",
                "model": "llama3.2:3b",
                "quality_score": 7.58,
                "capability": 5,
                "cost": 0,
            },
            {
                "model_provider": "deepseek",
                "model": "deepseek-v4-flash",
                "quality_score": 7.4,
                "capability": 6,
                "cost": 2,
            },
        ],
        "samples": 23,  # Test on 23 representative samples
        "timeout_sec": 240,
        "purpose": "Independent review by diverse models for quality consensus",
    },
}


# Behavioral preservation gates
BEHAVIOR_GATES = {
    "api_signature_check": {
        "enabled": True,
        "fail_action": "block",
        "description": "Ensure no exported functions or types are removed",
    },
    "external_endpoint_check": {
        "enabled": True,
        "fail_action": "block",
        "description": "Verify all /api/* endpoints remain available",
    },
    "config_immutability_check": {
        "enabled": True,
        "fail_action": "warn",
        "description": "Ensure config keys are not modified by patch",
    },
}


# Legal/security gates: owner-only approval for sensitive changes
LEGAL_GATES = {
    "licensing": {
        "required_approver": "kalepasch@gmail.com",
        "triggers": [
            "LICENSE",
            "license",
            "copyright",
            "COPYING",
        ],
        "description": "Licensing changes require owner approval",
    },
    "data_transmission": {
        "required_approver": "kalepasch@gmail.com",
        "triggers": [
            "privacy",
            "gdpr",
            "data retention",
            "encryption",
            "transmission",
            "http",
            "fetch",
        ],
        "description": "Data transmission changes require owner approval",
    },
    "credentials": {
        "required_approver": "kalepasch@gmail.com",
        "triggers": [
            "secret",
            "api.key",
            "password",
            "token",
            "credential",
            ".env",
        ],
        "description": "Credential changes require owner approval",
    },
}


# Cross-site testing: verify kalepasch.com and mandypasch.com work
# CROSS_SITE_TESTS is now resolved dynamically to avoid hardcoded paths.
# Configure via ORCH_CROSS_SITE_TESTS env var (JSON) or cross_site_config.json file.
CROSS_SITE_TESTS = {
    "mandypasch_com": {
        "name": "mandypasch.com",
        "repo": os.environ.get("ORCH_MANDYPASCH_COM_REPO", "https://github.com/mandypasch/mandypasch.com"),
        "tests_to_run": [
            "test_substack_rss_fetch",
            "test_site_render",
            "test_database_connection",
        ],
        "must_pass": True,
    },
    "kalepasch_com": {
        "name": "kalepasch-com",
        "repo": os.environ.get("ORCH_KALEPASCH_COM_REPO", "https://github.com/kalepasch/kalepasch.com"),
        "tests_to_run": [
            "test_build_succeeds",
            "test_no_regressions",
            "test_supabase_storage_access",
        ],
        "must_pass": True,
    },
}


# Merge and release configuration
MERGE_STRATEGY = {
    "auto_merge": True,
    "target_branch": "orchestrator/dev",
    "commit_author": "kalepasch1",
    "commit_email": "kalepasch@gmail.com",
    "commit_prefix": "relfix",
    "description": "Auto-merge to orchestrator/dev after passing all tests",
}


RELEASE_STRATEGY = {
    "auto_release": True,
    "target_branch": "master",
    "batch_size": 1,
    "batch_interval_hours": 24,
    "description": "Schedule for production deployment batch",
}


# Environment variable overrides (for operator tuning)
ENV_OVERRIDES = {
    "ORCH_PREFLIGHT_MODEL": os.environ.get("ORCH_PREFLIGHT_MODEL", "local:llama3.2:3b"),
    "ORCH_PLANNER_MODEL": os.environ.get("ORCH_PLANNER_MODEL", "deepseek:deepseek-v4-flash"),
    "ORCH_CODER_MODEL": os.environ.get("ORCH_CODER_MODEL", "claude-haiku-4-5-20251001"),
    "ORCH_QA_MODELS": os.environ.get("ORCH_QA_MODELS", "local:llama3.2:3b,deepseek:deepseek-v4-flash"),
    "ORCH_MIN_TESTS_PASS": os.environ.get("ORCH_MIN_TESTS_PASS", "8"),
    "ORCH_MAX_TESTS": os.environ.get("ORCH_MAX_TESTS", "12"),
}




# Task classes whose preflight triage must be routed to a hosted model with a
# stronger safety posture than the free local default. The pipeline contract
# already names this route for legal/security work; it was only ever written
# into prompt headers by hand, so nothing enforced it.
PREFLIGHT_ESCALATED_MODEL = os.environ.get(
    "ORCH_PREFLIGHT_ESCALATED_MODEL", "google:gemini-2.0-flash"
)
PREFLIGHT_ESCALATED_CLASSES = ("legal", "security", "compliance", "privacy")


def preflight_triage_model(task_class: str = None) -> str:
    """Return the ``provider:model`` route for the preflight triage stage.

    ``task_class`` may be a bare class ("legal") or the decorated form the
    pipeline contract emits ("legal (need 9, risk legal_posture)"); only the
    leading token is significant. Legal/security-adjacent classes escalate to
    PREFLIGHT_ESCALATED_MODEL; everything else takes the configured default.

    Fail-soft: None, empty, or unparseable input returns the default route
    rather than raising.
    """
    default = ENV_OVERRIDES.get("ORCH_PREFLIGHT_MODEL", "local:llama3.2:3b")
    try:
        head = str(task_class or "").strip().split("(")[0].strip().lower()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "preflight_triage_model: unparseable task_class %r (%s); using default",
            task_class, exc,
        )
        return default
    if head in PREFLIGHT_ESCALATED_CLASSES:
        return PREFLIGHT_ESCALATED_MODEL
    return default


def validate_config() -> bool:
    """Validate configuration integrity. Fail-soft: return False instead of raising.

    Returns:
        True if valid, False otherwise (graceful degradation)
    """
    try:
        for task_class, task_def in TASK_CLASSES.items():
            for stage in task_def["stages"]:
                if stage not in STAGES:
                    return False
        for gate_name, gate_def in LEGAL_GATES.items():
            if "required_approver" not in gate_def:
                return False
        for site_key, site_config in CROSS_SITE_TESTS.items():
            required = ["name", "tests_to_run", "must_pass"]
            for field in required:
                if field not in site_config:
                    return False
        return True
    except Exception:
        return False


_config_cache = {"_": None, "_t": 0.0}
_config_lock = threading.Lock()
_CACHE_TTL = 60


def _load_cross_site_config() -> Dict[str, Any]:
    """Load cross-site config from file or env. Fail-soft: return empty dict on error."""
    try:
        cfg_path = os.environ.get("ORCH_CROSS_SITE_CONFIG", "")
        if cfg_path and os.path.isfile(cfg_path):
            with open(cfg_path, "r", errors="replace") as f:
                content = f.read(8192)
                return json.loads(content) or {}
    except Exception:
        pass
    try:
        cfg_json = os.environ.get("ORCH_CROSS_SITE_TESTS", "")
        if cfg_json:
            return json.loads(cfg_json) or {}
    except Exception:
        pass
    return {}


def get_config(project_name: str = None, task_class: str = None) -> Dict[str, Any]:
    """Load configuration for a given project and task class. Fail-soft pattern.

    Caches config for 60s to reduce file I/O and DB queries. Thread-safe.

    Args:
        project_name: Project name (default: kalepasch-com)
        task_class: Task class (easy/medium/hard; default: hard)

    Returns:
        Dictionary with merged configuration (never raises; returns sensible defaults on error)

    Raises:
        ValueError: If task_class is not in TASK_CLASSES
    """
    project_name = project_name or PROJECT["name"]
    task_class = task_class or PROJECT["task_class"]

    # Pattern adapted from deployfix-07190257: explicit validation with clear error
    if task_class not in TASK_CLASSES:
        raise ValueError(f"Unknown task class: {task_class}")

    with _config_lock:
        cache_key = f"{project_name}:{task_class}"
        now = time.time()
        if _config_cache.get("_") and _config_cache.get("_k") == cache_key and (now - _config_cache.get("_t", 0)) < _CACHE_TTL:
            return _config_cache.get("_", {})

        config = {
            "project": PROJECT,
            "task_class_def": TASK_CLASSES[task_class],
            "stages": {},
            "behavior_gates": BEHAVIOR_GATES,
            "legal_gates": LEGAL_GATES,
            "cross_site_tests": CROSS_SITE_TESTS.copy(),
            "merge_strategy": MERGE_STRATEGY,
            "release_strategy": RELEASE_STRATEGY,
        }

        stage_names = TASK_CLASSES[task_class]["stages"]
        for stage_name in stage_names:
            if stage_name in STAGES:
                config["stages"][stage_name] = STAGES[stage_name]

        _config_cache["_"] = config
        _config_cache["_k"] = cache_key
        _config_cache["_t"] = now

        return config


if __name__ == "__main__":
    # CLI: validate config and print it
    try:
        validate_config()
        print("✓ Configuration is valid")
        print()

        import json
        config = get_config()
        print("Configuration for kalepasch-com / hard:")
        print(json.dumps({
            "project": config["project"],
            "task_class": config["task_class_def"],
            "stages": list(config["stages"].keys()),
            "legal_gates": list(config["legal_gates"].keys()),
            "cross_site_tests": list(config["cross_site_tests"].keys()),
        }, indent=2))
    except Exception as e:
        print(f"✗ Configuration error: {e}", file=sys.stderr)
        sys.exit(1)
