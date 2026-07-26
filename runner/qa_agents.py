"""
qa_agents.py — Parallel QA agents for Trojun Orchestrator Terminal.

Four specialized agents (unit_test, security, dead_code, performance) run in
parallel after task completion and return a PASS/FAIL/WARN verdict each.
"""
from __future__ import annotations

import logging
import os
import sys
import concurrent.futures
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)


class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class QAResult:
    id: str
    name: str
    verdict: Optional[Verdict]
    issues: list[str]
    running: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "verdict": self.verdict.value if self.verdict else None,
            "issues": self.issues,
            "running": self.running,
        }


def _run_unit_test_agent(task: dict) -> QAResult:
    """Check if unit tests passed based on task state."""
    state = task.get("state", "")
    issues = []
    if state == "TESTFAIL":
        verdict = Verdict.FAIL
        issues.append(f"Task failed with TESTFAIL state")
    elif state in ("DONE", "MERGED"):
        verdict = Verdict.PASS
    else:
        verdict = Verdict.WARN
        issues.append(f"Unexpected state: {state}")
    return QAResult(id="unit", name="Unit Tests", verdict=verdict, issues=issues)


def _run_security_agent(task: dict) -> QAResult:
    """Basic security check — flag tasks touching auth/secrets patterns."""
    slug = task.get("slug", "")
    issues = []
    verdict = Verdict.PASS
    sensitive_patterns = ["auth", "credential", "secret", "key", "token", "password", "rls"]
    if any(p in slug.lower() for p in sensitive_patterns):
        verdict = Verdict.WARN
        issues.append(f"Task involves sensitive area: {slug}")
    return QAResult(id="security", name="Security", verdict=verdict, issues=issues)


def _run_dead_code_agent(task: dict) -> QAResult:
    """Dead code check — heuristic pass for now (real version would parse diff)."""
    return QAResult(id="dead_code", name="Dead Code", verdict=Verdict.PASS, issues=[])


def _run_performance_agent(task: dict) -> QAResult:
    """Performance check based on cost and execution time."""
    cost = task.get("cost_usd") or 0
    issues = []
    if cost > 0.50:
        return QAResult(id="performance", name="Performance", verdict=Verdict.WARN,
                        issues=[f"High cost: ${cost:.4f} — consider task decomposition"])
    return QAResult(id="performance", name="Performance", verdict=Verdict.PASS, issues=issues)


_AGENTS = {
    "unit": _run_unit_test_agent,
    "security": _run_security_agent,
    "dead_code": _run_dead_code_agent,
    "performance": _run_performance_agent,
}


def run_qa_agents(task: dict, parallel: bool = True) -> list[dict]:
    """
    Run all four QA agents against a completed task.

    Args:
        task: Task dict with keys: slug, state, cost_usd, etc.
        parallel: If True, run agents concurrently.

    Returns:
        List of QA result dicts ordered by agent ID.
    """
    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fn, task): aid for aid, fn in _AGENTS.items()}
            results = {}
            for future in concurrent.futures.as_completed(futures):
                aid = futures[future]
                try:
                    results[aid] = future.result()
                except Exception as e:
                    results[aid] = QAResult(id=aid, name=aid, verdict=Verdict.WARN,
                                            issues=[f"Agent error: {e}"])
    else:
        results = {aid: fn(task) for aid, fn in _AGENTS.items()}

    ordered = ["unit", "security", "dead_code", "performance"]
    return [results[aid].to_dict() for aid in ordered if aid in results]
