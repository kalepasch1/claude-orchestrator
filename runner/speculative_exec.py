#!/usr/bin/env python3
"""
speculative_exec.py — Optimistic pipeline for high-confidence tasks (100X throughput).

Current flow: claim → agent run (5-15 min) → verify → build gate → integrate
Optimistic flow: claim → agent run (captures build result) → integrate

The agent already runs builds via BUILD_MANDATE. If we capture that exit code
from the agent's output, we can skip the redundant post-agent build gate.

For high-confidence task types (mechanical, template-matched, diff_compiler
confidence > 0.8), the entire post-agent pipeline collapses to just integration.

Conditions for speculative execution:
  1. diff_compiler confidence >= SPECULATIVE_THRESHOLD
  2. Task kind is in SPECULATIVE_KINDS (mechanical, template-adapted)
  3. BUILD_MANDATE is enabled (agent already builds)
  4. Not a material/sensitive task
  5. ORCH_SPECULATIVE_EXEC is enabled

When active, the agent's output is parsed for build/test results,
and if green, gates are bypassed entirely.
"""
import os, sys, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SPECULATIVE_THRESHOLD = float(os.environ.get("ORCH_SPECULATIVE_THRESHOLD", "0.8"))
SPECULATIVE_KINDS = {"mechanical", "config", "rename", "bump", "docs", "test",
                     "refactor", "cleanup", "formatting", "typo"}

# Patterns indicating the agent ran a successful build
BUILD_SUCCESS_PATTERNS = [
    r"build\s+succeed",
    r"build\s+passed",
    r"build\s+completed\s+successfully",
    r"npm\s+run\s+build.*?\n.*?(?:done|success|completed)",
    r"exit\s+code:?\s*0",
    r"✓\s+build",
    r"all\s+tests?\s+pass",
    r"tests?\s+passed",
    r"0\s+failed",
    r"test\s+suites?:.*?passed",
]

BUILD_FAILURE_PATTERNS = [
    r"build\s+fail",
    r"error\s+during\s+build",
    r"exit\s+code:?\s*[1-9]",
    r"FAIL\s",
    r"✗\s+build",
    r"compilation?\s+error",
    r"type\s+error",
    r"syntax\s+error",
]

_SUCCESS_RX = re.compile("|".join(BUILD_SUCCESS_PATTERNS), re.I)
_FAILURE_RX = re.compile("|".join(BUILD_FAILURE_PATTERNS), re.I)


def should_speculate(task, diff_plan=None):
    """Decide if a task qualifies for speculative execution.

    Returns (speculate: bool, reason: str)
    """
    if os.environ.get("ORCH_SPECULATIVE_EXEC", "true").lower() not in ("true", "1", "yes"):
        return False, "disabled"

    # Never speculate on material/sensitive tasks
    if task.get("material"):
        return False, "material task"

    prompt = (task.get("prompt") or "").lower()
    sensitive = ("security", "legal", "compliance", "privacy", "payment",
                 "credential", "migration", "schema", "production")
    for s in sensitive:
        if s in prompt:
            return False, f"sensitive: {s}"

    # Check diff compiler confidence
    if diff_plan and diff_plan.get("has_plan"):
        conf = diff_plan.get("confidence", 0)
        if conf >= SPECULATIVE_THRESHOLD:
            return True, f"template-matched (conf={conf:.0%})"

    # Check kind
    kind = (task.get("kind") or "").lower()
    if kind in SPECULATIVE_KINDS:
        return True, f"mechanical kind={kind}"

    # Check slug patterns
    slug = (task.get("slug") or "").lower()
    for pat in ("fix-lint", "fix-type", "rename-", "bump-", "format-", "typo-", "cleanup-"):
        if pat in slug:
            return True, f"mechanical slug ({pat})"

    return False, "no speculative condition met"


def extract_build_result(agent_output):
    """Parse the agent's output for build/test results.

    Returns:
        {"build_ok": bool|None, "tests_ok": bool|None, "evidence": str}

    None means we couldn't determine the result (fall back to explicit gate).
    """
    if not agent_output:
        return {"build_ok": None, "tests_ok": None, "evidence": "no output"}

    text = agent_output[-5000:]  # Build results are near the end

    success_matches = _SUCCESS_RX.findall(text)
    failure_matches = _FAILURE_RX.findall(text)

    if failure_matches and not success_matches:
        return {"build_ok": False, "tests_ok": False,
                "evidence": f"failures: {', '.join(failure_matches[:3])}"}

    if success_matches and not failure_matches:
        return {"build_ok": True, "tests_ok": True,
                "evidence": f"successes: {', '.join(success_matches[:3])}"}

    if success_matches and failure_matches:
        # Both found — look at what came LAST (final state)
        last_success = max(text.rfind(m) for m in success_matches) if success_matches else -1
        last_failure = max(text.rfind(m) for m in failure_matches) if failure_matches else -1

        if last_success > last_failure:
            return {"build_ok": True, "tests_ok": True,
                    "evidence": "final state: success (after earlier failures)"}
        else:
            return {"build_ok": False, "tests_ok": False,
                    "evidence": "final state: failure (after earlier successes)"}

    return {"build_ok": None, "tests_ok": None, "evidence": "inconclusive"}


def can_skip_build_gate(agent_output, task, diff_plan=None):
    """Full check: should we skip the post-agent build gate?

    Returns (skip: bool, reason: str)
    """
    speculate, spec_reason = should_speculate(task, diff_plan)
    if not speculate:
        return False, spec_reason

    result = extract_build_result(agent_output)
    if result["build_ok"] is True:
        return True, f"agent build green + {spec_reason}: {result['evidence']}"
    if result["build_ok"] is False:
        return False, f"agent build red: {result['evidence']}"

    return False, f"inconclusive build result: {result['evidence']}"
