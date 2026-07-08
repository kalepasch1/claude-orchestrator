#!/usr/bin/env python3
"""
fast_path.py — Graduated autonomy fast-path (100X on high-trust patterns).

Level 4 tasks currently skip gates but still run through the full pre-agent
hook chain (debate compression, template injection, bidding, etc). For L4
tasks, this module provides a fast-path that skips EVERYTHING:

  L4 fast-path: raw prompt → agent → merge (no pre-hooks, no gates)
  L3 fast-path: minimal pre-hooks (just knowledge query) → agent → minimal gates
  L2 and below: full pipeline

Combined with unified_knowledge, the L3 path does a single knowledge query
instead of 6+ separate lookups.

Usage:
    import fast_path
    fp = fast_path.check(task, agent_id, domain)
    if fp["level"] >= 4:
        # Skip ALL pre-hooks and gates
    elif fp["level"] >= 3:
        # Minimal pipeline via unified_knowledge
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAST_PATH_ENABLED = os.environ.get("ORCH_FAST_PATH", "true").lower() in ("true", "1", "yes")


def check(task, agent_id="", domain=""):
    """Check if task qualifies for fast-path execution.

    Returns: {
        level: int (0-4),
        skip_pre_hooks: bool,
        skip_gates: bool,
        skip_all: bool,
        use_unified_knowledge: bool,
        reason: str,
    }
    """
    if not FAST_PATH_ENABLED:
        return {"level": 0, "skip_pre_hooks": False, "skip_gates": False,
                "skip_all": False, "use_unified_knowledge": False, "reason": "disabled"}

    try:
        import graduated_autonomy
        level = graduated_autonomy.trust_level(task, agent_id, domain)
        gates = graduated_autonomy.gates_to_skip(level)
    except Exception:
        return {"level": 0, "skip_pre_hooks": False, "skip_gates": False,
                "skip_all": False, "use_unified_knowledge": False, "reason": "autonomy check failed"}

    if level >= 4:
        # L4: skip EVERYTHING — raw prompt → agent → merge
        return {
            "level": 4,
            "skip_pre_hooks": True,
            "skip_gates": True,
            "skip_all": True,
            "use_unified_knowledge": False,
            "reason": f"L4 trust: {agent_id} in {domain}",
            "gates": gates,
        }
    elif level >= 3:
        # L3: minimal pipeline — single unified knowledge query, skip most gates
        return {
            "level": 3,
            "skip_pre_hooks": True,  # skip individual hooks
            "skip_gates": False,
            "skip_all": False,
            "use_unified_knowledge": True,  # use unified_knowledge.query() instead
            "reason": f"L3 trust: single knowledge query path",
            "gates": gates,
        }
    elif level >= 2:
        # L2: skip some hooks but keep gates
        return {
            "level": 2,
            "skip_pre_hooks": False,
            "skip_gates": False,
            "skip_all": False,
            "use_unified_knowledge": True,  # still use unified for efficiency
            "reason": f"L2: unified knowledge + full gates",
            "gates": gates,
        }
    else:
        return {
            "level": level,
            "skip_pre_hooks": False,
            "skip_gates": False,
            "skip_all": False,
            "use_unified_knowledge": False,
            "reason": f"L{level}: full pipeline",
            "gates": gates,
        }


def run():
    """Periodic: report fast-path stats."""
    print("[fast-path] module loaded — fast-path checks run inline per-task")
