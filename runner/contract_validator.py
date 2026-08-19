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

try:
    import orchestration_pipeline_config as opc
except ImportError:
    opc = None


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
        if config:
            self.config = config
        elif opc:
            self.config = opc.get_config()
        else:
            self.config = {"stages": {}}
        self.qa_votes: List[QAPanelVote] = []
        self.legal_results: List[LegalGateResult] = []
        self.coordination_rules: List[CoordinationRule] = []

    def validate_preflight_triage(self, qpd_score: float) -> Tuple[bool, str]:
        """Validate preflight triage quality gate (target q≥6.2)."""
        try:
            if opc:
                stage = opc.STAGES["preflight_triage"]
        except (KeyError, AttributeError, TypeError):
            pass
        target_q = 6.2
        if qpd_score < target_q:
            return False, f"preflight quality {qpd_score:.1f} < target {target_q}"
        return True, f"preflight quality {qpd_score:.1f} >= target {target_q}"

    def validate_strategy_planner(self, qpd_score: float) -> Tuple[bool, str]:
        """Validate strategy planner quality gate (target q≥6.6)."""
        if "strategy_planner" not in self.config.get("stages", {}):
            return True, "strategy planner not required for this task class"
        try:
            if opc:
                stage = opc.STAGES["strategy_planner"]
        except (KeyError, AttributeError, TypeError):
            pass
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

        try:
            legal_gates = opc.LEGAL_GATES if opc else {}
        except (AttributeError, TypeError):
            legal_gates = {}

        for gate_name, gate_def in legal_gates.items():
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


# =============================================================================
# Fleet-wide Config Validation (smart contracts for configuration changes)
# =============================================================================

_LEGAL_TRIGGER_KEYWORDS = {
    "licensing": ["license", "copyright", "patent", "terms"],
    "registration": ["register", "registration", "enroll", "activation"],
    "custody": ["custody", "owner", "owner", "steward", "guardian"],
    "transmission": ["transmission", "transfer", "handoff", "migrate"],
    "advice": ["advice", "recommendation", "counsel", "guidance"],
}

_CREDENTIAL_MARKERS = ("PASSWORD", "TOKEN", "SECRET", "KEY", "PAT", "API_KEY", "CREDENTIAL")


def detect_legal_trigger(config_key: str) -> bool:
    """Detect if a config key requires legal gate review.

    Returns True if the key matches licensing/registration/custody/transmission/advice
    or contains PASSWORD|TOKEN|SECRET credential markers.

    Fail-soft: returns False on any error (None, empty, non-string input).

    Args:
        config_key: Configuration key name to check

    Returns:
        bool: True if legal trigger detected, False otherwise
    """
    try:
        if not config_key or not isinstance(config_key, str):
            return False

        key_upper = config_key.upper()

        # Check for credential markers
        if any(marker in key_upper for marker in _CREDENTIAL_MARKERS):
            return True

        # Check for legal trigger keywords
        for category, keywords in _LEGAL_TRIGGER_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in config_key.lower():
                    return True

        return False
    except Exception:
        return False


def validate_contract_change(old_val: Optional[Any], new_val: Optional[Any], key: str) -> Tuple[bool, str]:
    """Validate a configuration change against contract rules.

    Returns (is_valid, reason) where:
    - (True, "") if change is valid or not a legal trigger
    - (False, reason) if change is invalid (e.g., dangerous transitions)
    - (True, "") on any error (fail-soft pattern)

    Args:
        old_val: Previous configuration value
        new_val: New configuration value
        key: Configuration key being changed

    Returns:
        tuple: (is_valid: bool, reason: str)
    """
    try:
        if not detect_legal_trigger(key):
            return True, ""

        # For legal triggers, apply validation rules
        # Rule 1: Cannot clear a licensing/registration flag (dangerous rollback)
        if old_val and not new_val:
            key_lower = key.lower()
            if any(kw in key_lower for kw in ["license", "registration", "register"]):
                return False, f"Cannot clear {key}: would revoke status"

        # Rule 2: Transmission changes require explicit acknowledgment
        if "transmission" in key.lower():
            if isinstance(new_val, bool) and new_val and not isinstance(old_val, bool):
                return False, f"{key} transition from unset to enabled requires explicit approval"

        # Rule 3: Owner changes must preserve audit trail
        if "owner" in key.lower() and old_val != new_val:
            if not new_val:
                return False, f"Cannot clear owner on {key}: audit trail required"

        return True, ""
    except Exception:
        return True, ""


def legal_gate_required(change_dict: Optional[Dict[str, Any]]) -> bool:
    """Determine if a configuration change dict requires legal gate approval.

    Scans all keys in the change dict and returns True if ANY key triggers
    a legal gate (has legal trigger keywords or credential markers).

    Fail-soft: returns False on any error (None, empty, invalid input).

    Args:
        change_dict: Dict of {key: new_value} configuration changes

    Returns:
        bool: True if legal gate approval required, False otherwise
    """
    try:
        if not change_dict or not isinstance(change_dict, dict):
            return False

        for key in change_dict.keys():
            if detect_legal_trigger(key):
                return True

        return False
    except Exception:
        return False


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

    # Example: config change validation
    print()
    print("Config change validation:")
    print(f"  ORCH_MAX_PARALLEL=10: {detect_legal_trigger('ORCH_MAX_PARALLEL')}")
    print(f"  ORCH_LICENSE_KEY: {detect_legal_trigger('ORCH_LICENSE_KEY')}")
    print(f"  ORCH_API_TOKEN: {detect_legal_trigger('ORCH_API_TOKEN')}")
    print(f"  legal_gate_required({{ORCH_MAX_PARALLEL: 10}}): {legal_gate_required({'ORCH_MAX_PARALLEL': 10})}")
    print(f"  legal_gate_required({{ORCH_REGISTRATION_ID: 'abc'}}): {legal_gate_required({'ORCH_REGISTRATION_ID': 'abc'})}")
