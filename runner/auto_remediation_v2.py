"""Closed-loop remediation: propose, validate, gate protected operations, monitor."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
import evidence_bus

PROTECTED_OPERATIONS = {"submit_filing", "delete_evidence", "change_constitution", "external_notification"}

@dataclass(frozen=True)
class RemediationResult:
    status: str
    reason: str
    plan: dict[str, Any]


class AutoRemediationEngineV2:
    def remediate(self, app_id: str, issue: dict[str, Any], generate: Callable[[dict[str, Any]], dict[str, Any]],
                  validate: Callable[[dict[str, Any]], bool], apply: Callable[[dict[str, Any]], None]) -> RemediationResult:
        plan = generate(dict(issue))
        operation = plan.get("operation", "")
        evidence_bus.append(app_id, "compliance.remediation.proposed", str(issue.get("id", "unknown")), plan)
        if operation in PROTECTED_OPERATIONS or plan.get("requires_human_approval"):
            return RemediationResult("approval_required", "protected operation", plan)
        if not validate(plan):
            return RemediationResult("rejected", "validation failed", plan)
        apply(plan)
        evidence_bus.append(app_id, "compliance.remediation.applied", str(issue.get("id", "unknown")), plan)
        return RemediationResult("applied", "validated and applied", plan)
