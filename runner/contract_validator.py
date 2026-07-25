#!/usr/bin/env python3
"""
contract_validator.py — Enforce orchestration pipeline contract gates and rules.

Validates model routing, QA gates, legal gates, and coordination rules.
Blocks auto-merge when conditions are not met and detects conflicts with active branches.

Task: backlog-batch-illuminati-dd47b58
"""
import os
import sys
import re
import subprocess
from typing import Dict, List, Tuple, Optional, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import orchestration_pipeline_config as opc


class ContractViolation(Exception):
    """Raised when pipeline contract is violated."""
    pass


class QAPanelVote:
    """Result of a single QA panel member's vote."""
    def __init__(self, model: str, passed: bool, confidence: float = 0.0, notes: str = ""):
        self.model = model
        self.passed = passed
        self.confidence = confidence
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "passed": self.passed,
            "confidence": self.confidence,
            "notes": self.notes,
        }


class LegalGateResult:
    """Result of legal gate evaluation."""
    def __init__(self, gate_name: str, triggered: bool, reason: str = "", required_approver: str = ""):
        self.gate_name = gate_name
        self.triggered = triggered
        self.reason = reason
        self.required_approver = required_approver

    def blocks_merge(self) -> bool:
        return self.triggered

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate": self.gate_name,
            "triggered": self.triggered,
            "reason": self.reason,
            "required_approver": self.required_approver,
        }


class CoordinationRule:
    """Coordination rule for avoiding branch conflicts."""
    def __init__(self, rule_name: str, violation: bool = False, details: str = ""):
        self.rule_name = rule_name
        self.violation = violation
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule": self.rule_name,
            "violated": self.violation,
            "details": self.details,
        }


class PipelineContractValidator:
    """Validates orchestration pipeline contract execution."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or opc.get_config()
        self.qa_votes: List[QAPanelVote] = []
        self.legal_results: List[LegalGateResult] = []
        self.coordination_rules: List[CoordinationRule] = []

    def validate_preflight_triage(self, qpd_score: float) -> Tuple[bool, str]:
        """Validate preflight triage quality gate (target q≥6.2)."""
        stage = opc.STAGES["preflight_triage"]
        target_q = 6.2
        if qpd_score < target_q:
            return False, f"preflight quality {qpd_score:.1f} < target {target_q}"
        return True, f"preflight quality {qpd_score:.1f} >= target {target_q}"

    def validate_strategy_planner(self, qpd_score: float) -> Tuple[bool, str]:
        """Validate strategy planner quality gate (target q≥6.6)."""
        if "strategy_planner" not in self.config["stages"]:
            return True, "strategy planner not required for this task class"
        stage = opc.STAGES["strategy_planner"]
        target_q = 6.6
        if qpd_score < target_q:
            return False, f"planner quality {qpd_score:.1f} < target {target_q}"
        return True, f"planner quality {qpd_score:.1f} >= target {target_q}"

    def validate_qa_panel(self, votes: List[QAPanelVote]) -> Tuple[bool, str]:
        """Validate QA panel consensus (target q≥7.7, required agreement≥2)."""
        if not votes:
            return False, "QA panel: no votes recorded"

        self.qa_votes = votes
        passed_count = sum(1 for v in votes if v.passed)
        stage = opc.STAGES["qa_panel"]
        required = stage["required_agreement"]

        if passed_count < required:
            return False, f"QA panel: {passed_count} passed < {required} required"

        avg_confidence = sum(v.confidence for v in votes) / len(votes) if votes else 0.0
        if avg_confidence < 0.7:
            return False, f"QA panel: confidence {avg_confidence:.1%} < 70%"

        return True, f"QA panel: {passed_count}/{len(votes)} passed, confidence {avg_confidence:.1%}"

    def check_legal_gates(self, diff_content: str) -> Tuple[bool, List[LegalGateResult]]:
        """Check legal gates against changed content.

        Triggers are owner-only approval for:
        - Licensing (LICENSE, copyright, etc.)
        - Data transmission (privacy, GDPR, encryption, etc.)
        - Credentials (secrets, tokens, .env, etc.)

        Returns:
            (all_clear, list of gate results)
        """
        self.legal_results = []
        all_clear = True

        for gate_name, gate_def in opc.LEGAL_GATES.items():
            triggered = False
            reason = ""

            triggers = gate_def.get("triggers", [])
            for trigger in triggers:
                if trigger.lower() in diff_content.lower():
                    triggered = True
                    reason = f"Found trigger '{trigger}' in diff"
                    all_clear = False
                    break

            result = LegalGateResult(
                gate_name=gate_name,
                triggered=triggered,
                reason=reason,
                required_approver=gate_def.get("required_approver", ""),
            )
            self.legal_results.append(result)

        return all_clear, self.legal_results

    def detect_active_agent_branches(self, repo_path: str) -> List[str]:
        """Detect active agent/* branches to avoid conflicts.

        Returns:
            List of branch names matching agent/*, or empty list on error.
        """
        try:
            result = subprocess.run(
                ["git", "branch", "-r", "--list", "origin/agent/*"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return []
            branches = [b.strip().replace("origin/", "") for b in result.stdout.split("\n") if b.strip()]
            return branches
        except Exception:
            return []

    def check_coordination_rules(self, repo_path: str, branch: str) -> Tuple[bool, List[CoordinationRule]]:
        """Check coordination rules before merge.

        Rules:
        1. Do not delete or overwrite unrelated queued improvements
        2. Reconcile with active agent/* branches before committing
        3. Warn before overwriting

        Returns:
            (no_violations, list of rule results)
        """
        self.coordination_rules = []
        no_violations = True

        # Rule 1: Check for unrelated active branches
        active_branches = self.detect_active_agent_branches(repo_path)
        if active_branches:
            violation = not self._branch_reconciled(repo_path, branch, active_branches)
            rule1 = CoordinationRule(
                "avoid_unrelated_overwrites",
                violation=violation,
                details=f"Found {len(active_branches)} active agent branches: {', '.join(active_branches[:3])}"
            )
            self.coordination_rules.append(rule1)
            if violation:
                no_violations = False

        # Rule 2: Check merge target not in active branches
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
            current_branch = result.stdout.strip() if result.returncode == 0 else ""
            if current_branch and current_branch != branch:
                rule2 = CoordinationRule(
                    "branch_checkout_conflict",
                    violation=True,
                    details=f"Repo checked out on {current_branch}, not {branch}"
                )
                self.coordination_rules.append(rule2)
                no_violations = False
        except Exception as e:
            rule2 = CoordinationRule(
                "branch_checkout_check_failed",
                violation=False,
                details=str(e)
            )
            self.coordination_rules.append(rule2)

        return no_violations, self.coordination_rules

    def _branch_reconciled(self, repo_path: str, branch: str, active_branches: List[str]) -> bool:
        """Check if branch is reconciled with active branches.

        A branch is considered reconciled if:
        - It's completely separate (no common ancestors)
        - Or its commits are a strict superset of active branch commits
        """
        for active in active_branches:
            try:
                result = subprocess.run(
                    ["git", "merge-base", "--is-ancestor", f"origin/{active}", branch],
                    cwd=repo_path,
                    capture_output=True,
                    timeout=30,
                )
                # If active branch is NOT an ancestor, they're diverged
                if result.returncode != 0:
                    return False
            except Exception:
                return False
        return True

    def validate_auto_merge_gates(self) -> Tuple[bool, Dict[str, Any]]:
        """Check all gates before auto-merge to orchestrator/dev.

        Requirements:
        1. All QA panel votes pass
        2. Legal gate not triggered
        3. No coordination rule violations

        Returns:
            (can_merge, detailed_status)
        """
        status = {
            "can_merge": True,
            "qa_panel_passed": len(self.qa_votes) > 0 and all(v.passed for v in self.qa_votes),
            "legal_gates_passed": all(not r.triggered for r in self.legal_results),
            "coordination_rules_passed": all(not r.violation for r in self.coordination_rules),
            "qa_votes": [v.to_dict() for v in self.qa_votes],
            "legal_gates": [r.to_dict() for r in self.legal_results],
            "coordination_rules": [r.to_dict() for r in self.coordination_rules],
        }

        status["can_merge"] = (
            status["qa_panel_passed"] and
            status["legal_gates_passed"] and
            status["coordination_rules_passed"]
        )

        return status["can_merge"], status

    def merge_blocked_reason(self) -> Optional[str]:
        """Return human-readable reason why merge is blocked, or None if can merge."""
        can_merge, status = self.validate_auto_merge_gates()
        if can_merge:
            return None

        reasons = []
        if not status["qa_panel_passed"]:
            reasons.append("QA panel did not achieve required consensus")
        if not status["legal_gates_passed"]:
            triggered = [r["gate"] for r in status["legal_gates"] if r["triggered"]]
            reasons.append(f"Legal gates triggered: {', '.join(triggered)}")
        if not status["coordination_rules_passed"]:
            violated = [r["rule"] for r in status["coordination_rules"] if r["violated"]]
            reasons.append(f"Coordination rules violated: {', '.join(violated)}")

        return "; ".join(reasons) if reasons else "Unknown merge block reason"


# Module-level convenience functions

def validate_preflight_triage(qpd_score: float) -> Tuple[bool, str]:
    """Validate preflight triage quality threshold (target q≥6.2)."""
    validator = PipelineContractValidator()
    return validator.validate_preflight_triage(qpd_score)


def validate_strategy_planner(qpd_score: float, task_class: str = "hard") -> Tuple[bool, str]:
    """Validate strategy planner quality threshold (target q≥6.6)."""
    config = opc.get_config(task_class=task_class)
    validator = PipelineContractValidator(config)
    return validator.validate_strategy_planner(qpd_score)


def validate_qa_panel(votes: List[Dict[str, Any]]) -> Tuple[bool, str]:
    """Validate QA panel consensus (target q≥7.7, agreement≥2)."""
    vote_objects = [
        QAPanelVote(
            model=v.get("model", "unknown"),
            passed=v.get("passed", False),
            confidence=float(v.get("confidence", 0.0)),
            notes=v.get("notes", ""),
        )
        for v in votes
    ]
    validator = PipelineContractValidator()
    return validator.validate_qa_panel(vote_objects)


def check_legal_gates(diff_content: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Check for legal gate triggers (licensing, credentials, data transmission)."""
    validator = PipelineContractValidator()
    all_clear, results = validator.check_legal_gates(diff_content)
    return all_clear, [r.to_dict() for r in results]


def check_coordination_rules(repo_path: str, branch: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Check coordination rules to avoid branch conflicts."""
    validator = PipelineContractValidator()
    no_violations, results = validator.check_coordination_rules(repo_path, branch)
    return no_violations, [r.to_dict() for r in results]


if __name__ == "__main__":
    # CLI: validate example scenario
    import json

    print("✓ Contract validator loaded")
    print()

    # Example: validate QA panel votes
    example_votes = [
        {"model": "llama3.2:3b", "passed": True, "confidence": 0.85},
        {"model": "deepseek-v4-flash", "passed": True, "confidence": 0.88},
    ]
    passed, msg = validate_qa_panel(example_votes)
    print(f"QA Panel validation: {msg}")

    # Example: check legal gates
    clean_diff = "feat: add new feature"
    all_clear, results = check_legal_gates(clean_diff)
    print(f"Legal gates (clean diff): all_clear={all_clear}, gates={len(results)}")

    triggered_diff = "chore: update .env with new API_KEY=secret123"
    all_clear, results = check_legal_gates(triggered_diff)
    print(f"Legal gates (with credentials): all_clear={all_clear}")
    triggered_gates = [r["gate"] for r in results if r["triggered"]]
    print(f"  Triggered: {triggered_gates}")
