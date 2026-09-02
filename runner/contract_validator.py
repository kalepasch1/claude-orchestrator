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

        # A DIFF THAT IS NOT TEXT FAILS THE GATE, IT DOES NOT CRASH IT (2026-08-26).
        #
        # This went straight to `trigger.lower() in diff_content.lower()`, so
        # check_legal_gates(None) raised AttributeError out of a compliance gate on
        # the merge path. An exception there is the worst of the three outcomes: the
        # gate neither passes nor blocks, it just breaks its caller, and whether the
        # change was reviewed depends on how that caller happens to handle errors.
        #
        # Failing CLOSED rather than treating it as clear, for the reason build_gate
        # states about its own undeterminable case: a gate that cannot see the change
        # has not cleared it. An empty STRING is different and still scans normally —
        # "no changes" is a real answer, "the diff never arrived" is not.
        if not isinstance(diff_content, str):
            self.legal_results = [LegalGateResult(
                gate_name="diff_unavailable",
                triggered=True,
                reason=(f"diff_content was {type(diff_content).__name__}, not text; "
                        "the legal gates had nothing to scan"),
                required_approver="owner",
            )]
            return False, self.legal_results

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


# ── Config-key legal gates ────────────────────────────────────────────────────
#
# runner/tests/test_contract_validator.py has imported these three names since
# it was written; they were never implemented, so the whole file failed at
# COLLECTION — pytest reported one error and refused to run the suite at all,
# which is why the gap survived. The 409-line test is a complete specification,
# and this is the implementation it describes.
#
# check_legal_gates() above scans a DIFF. These scan a CONFIG KEY, which is the
# other half: the fleet applies config changes without producing a diff, so a
# licence key could be cleared without anything diff-shaped to inspect.
#
# Everything here fails SOFT (permit, empty reason) on bad input. A validator
# that raises inside a config applier converts a questionable change into an
# outage, which is strictly worse than the change.

# Substring matched against a lowercased key. Deliberately substring, not token:
# UNLICENSED_MODE and HOMEOWNER_POLICY must both trip, and a key naming scheme
# nobody has invented yet should trip too. False positives here cost one
# approval click; false negatives cost a licence.
_CONTRACT_TRIGGERS = {
    'license':      ('license',),
    'registration': ('registration', 'enroll'),
    'custody':      ('custody', 'owner', 'steward'),
    'transmission': ('transmission', 'transfer', 'migration'),
    'advice':       ('advice', 'recommendation', 'guidance'),
}

# Credential markers. Separate from the contract families above because the
# rules differ: rotating or removing a secret is ordinary operations, whereas
# clearing a licence is a legal event. Both require the gate; only one is
# refused outright.
_CREDENTIAL_MARKERS = ('password', 'token', 'secret', 'key', 'pat', 'credential')


def _matched_contract_family(key: str) -> Optional[str]:
    """Contract family a key belongs to, or None. Assumes key is already lowered."""
    for family, words in _CONTRACT_TRIGGERS.items():
        if any(w in key for w in words):
            return family
    return None


def detect_legal_trigger(key: Any) -> bool:
    """
    True when a config key touches a licensing, registration, custody,
    transmission or advice contract, or carries a credential.

    Case-insensitive substring match. Non-string input is False, not an error:
    callers iterate raw config dicts that may hold non-string keys.
    """
    if not isinstance(key, str) or not key:
        return False
    lowered = key.lower()
    if _matched_contract_family(lowered) is not None:
        return True
    return any(marker in lowered for marker in _CREDENTIAL_MARKERS)


def validate_contract_change(old_value: Any, new_value: Any, key: Any) -> Tuple[bool, str]:
    """
    Decide whether one config change may proceed.

    Returns (permitted, reason). Reason is '' when permitted.

    Refused:
      - clearing a contract value (licence, registration, custody/owner,
        transmission, advice). Revocation must be deliberate and leave an audit
        trail, not fall out of a config apply.
      - switching transmission on from an unset state. There is no prior value
        to show anyone that the transfer was ever authorised.

    Permitted: everything else, including replacing one contract value with
    another — that is an amendment, and it keeps its audit trail.

    Credential keys gate (detect_legal_trigger is True) but are not refused
    here: rotating a secret is routine, and blocking it would push operators
    toward editing config out of band.
    """
    try:
        if not isinstance(key, str) or not key:
            return True, ''
        lowered = key.lower()
        family = _matched_contract_family(lowered)
        if family is None:
            return True, ''

        if new_value is None and old_value is not None:
            return False, (
                f"Refusing to clear {family} value '{key}': revoking a {family} "
                f"contract requires an explicit, audited action, not a config apply."
            )

        if family == 'transmission' and old_value is None and new_value:
            return False, (
                f"Refusing to enable transmission via '{key}' from an unset state: "
                f"there is no prior value evidencing that the transfer was authorised."
            )

        return True, ''
    except Exception:
        # Fail soft. See the module note above.
        return True, ''


def legal_gate_required(changes: Any) -> bool:
    """
    True when any key in a config change set needs the legal gate.

    Non-dict input is False rather than an error, and non-string keys are
    skipped, because this runs over config payloads assembled elsewhere.
    """
    if not isinstance(changes, dict) or not changes:
        return False
    try:
        return any(detect_legal_trigger(k) for k in changes)
    except Exception:
        return False


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
