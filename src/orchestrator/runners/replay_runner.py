"""ReplayRunner: Counterfactual replay of past task decisions for policy optimization.

Loads past task execution records, re-evaluates decisions using current policies,
compares past vs current decisions to identify divergence points, and reports findings.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, asdict

from src.orchestrator.policies import DecisionContext, PolicyDecision, DefaultPolicy

log = logging.getLogger(__name__)


@dataclass
class ReplayRecord:
    """Captured past decision for replay."""
    task_id: str
    past_decision: str
    past_policy: str
    task_data: Dict[str, Any]
    available_routes: List[str]
    recorded_at: str
    outcome: Optional[str] = None


@dataclass
class DivergenceReport:
    """Result of comparing past vs current decision."""
    task_id: str
    diverged: bool
    past_decision: str
    current_decision: str
    past_policy: str
    current_policy: str
    confidence_shift: float
    reason: str
    timestamp: str


class ReplayRunner:
    """Replays past task decisions against current policies to detect divergences.

    Usage:
        runner = ReplayRunner(policies=[DefaultPolicy(), ...])
        runner.load_history(limit=100)
        reports = runner.run_replay()
        runner.persist_results(reports)
    """

    def __init__(self, policies: Optional[List] = None, db=None):
        """Initialize replay runner.

        Args:
            policies: List of policy objects with evaluate() methods.
            db: Database client for loading/storing results (optional).
        """
        self.policies = policies or [DefaultPolicy()]
        self.db = db
        self.records: List[ReplayRecord] = []
        self.divergence_reports: List[DivergenceReport] = []
        self.stats = {
            "total_replayed": 0,
            "divergences_found": 0,
            "no_change": 0,
            "policies_changed": set(),
        }

    def load_history(self, limit: int = 10, days_back: int = 7) -> int:
        """Load past task execution records from storage.

        Args:
            limit: Maximum number of records to load.
            days_back: Only load records from the last N days.

        Returns:
            Number of records loaded.
        """
        if self.db:
            return self._load_from_db(limit, days_back)
        return self._load_demo_records()

    def _load_from_db(self, limit: int, days_back: int) -> int:
        """Load records from database."""
        try:
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
            # Query task_executions table for past decisions
            records = self.db.select("task_executions", {
                "select": "*",
                "created_at": f"gte.{cutoff}",
                "limit": str(limit),
                "order": "created_at.desc",
            }) or []

            for rec in records:
                try:
                    self.records.append(ReplayRecord(
                        task_id=rec.get("task_id", ""),
                        past_decision=rec.get("routed_to", ""),
                        past_policy=rec.get("routing_policy", "unknown"),
                        task_data=json.loads(rec.get("task_data", "{}"))
                        if isinstance(rec.get("task_data"), str) else rec.get("task_data", {}),
                        available_routes=json.loads(rec.get("available_routes", "[]"))
                        if isinstance(rec.get("available_routes"), str) else rec.get("available_routes", []),
                        recorded_at=rec.get("created_at", datetime.utcnow().isoformat()),
                        outcome=rec.get("outcome"),
                    ))
                except (json.JSONDecodeError, KeyError) as e:
                    log.warning(f"Skipping malformed record {rec.get('task_id')}: {e}")
                    continue

            log.info(f"Loaded {len(self.records)} execution records from database")
            return len(self.records)
        except Exception as e:
            log.error(f"Failed to load history from database: {e}")
            return self._load_demo_records()

    def _load_demo_records(self) -> int:
        """Load demo records for testing without database."""
        demo = [
            ReplayRecord(
                task_id="task-001",
                past_decision="route-a",
                past_policy="default_roundrobin",
                task_data={"project_id": "proj1", "model_id": "gpt4"},
                available_routes=["route-a", "route-b", "route-c"],
                recorded_at=datetime.utcnow().isoformat(),
                outcome="success",
            ),
            ReplayRecord(
                task_id="task-002",
                past_decision="route-b",
                past_policy="affinity_based",
                task_data={"project_id": "proj2", "model_id": "claude"},
                available_routes=["route-a", "route-b"],
                recorded_at=datetime.utcnow().isoformat(),
                outcome="success",
            ),
            ReplayRecord(
                task_id="task-003",
                past_decision="route-a",
                past_policy="default_roundrobin",
                task_data={"project_id": "proj1", "model_id": "gpt4"},
                available_routes=["route-a", "route-b"],
                recorded_at=datetime.utcnow().isoformat(),
                outcome="failed",
            ),
        ]
        self.records = demo
        log.info(f"Loaded {len(demo)} demo records (no database)")
        return len(demo)

    def run_replay(self) -> List[DivergenceReport]:
        """Re-evaluate all loaded records against current policies.

        Returns:
            List of divergence reports.
        """
        self.divergence_reports = []
        for record in self.records:
            try:
                report = self._replay_single(record)
                self.divergence_reports.append(report)

                if report.diverged:
                    self.stats["divergences_found"] += 1
                    self.stats["policies_changed"].add(report.past_policy)
                else:
                    self.stats["no_change"] += 1
            except Exception as e:
                log.error(f"Error replaying task {record.task_id}: {e}")
                continue

        self.stats["total_replayed"] = len(self.records)
        log.info(f"Replay complete: {self.stats['total_replayed']} tasks, "
                f"{self.stats['divergences_found']} divergences, "
                f"{self.stats['no_change']} unchanged")
        return self.divergence_reports

    def _replay_single(self, record: ReplayRecord) -> DivergenceReport:
        """Re-evaluate a single past decision."""
        context = DecisionContext(
            task_id=record.task_id,
            task_data=record.task_data,
            available_routes=record.available_routes,
        )

        # Find policy that matches the past decision's policy name
        matching_policy = None
        for policy in self.policies:
            if policy.name == record.past_policy:
                matching_policy = policy
                break

        # If policy not found, use first available
        if not matching_policy:
            matching_policy = self.policies[0] if self.policies else DefaultPolicy()
            log.warning(f"Policy {record.past_policy} not found for task {record.task_id}, "
                       f"using {matching_policy.name}")

        # Evaluate with current policy
        current_decision = matching_policy.evaluate(context)

        # Compare
        diverged = record.past_decision != current_decision.chosen_route
        confidence_shift = abs(1.0 - current_decision.confidence)
        reason = f"Policy {matching_policy.name} changed route from {record.past_decision} to {current_decision.chosen_route}" \
            if diverged else f"Decision stable under {matching_policy.name}"

        return DivergenceReport(
            task_id=record.task_id,
            diverged=diverged,
            past_decision=record.past_decision,
            current_decision=current_decision.chosen_route,
            past_policy=record.past_policy,
            current_policy=matching_policy.name,
            confidence_shift=confidence_shift,
            reason=reason,
            timestamp=datetime.utcnow().isoformat(),
        )

    def persist_results(self, reports: Optional[List[DivergenceReport]] = None) -> bool:
        """Persist replay results to storage.

        Args:
            reports: Reports to persist (defaults to self.divergence_reports).

        Returns:
            True if successful, False otherwise.
        """
        reports = reports or self.divergence_reports
        if not reports:
            return True

        if self.db:
            return self._persist_to_db(reports)
        return self._persist_to_local(reports)

    def _persist_to_db(self, reports: List[DivergenceReport]) -> bool:
        """Persist reports to database."""
        try:
            for report in reports:
                self.db.insert("replay_results", {
                    "task_id": report.task_id,
                    "diverged": report.diverged,
                    "past_decision": report.past_decision,
                    "current_decision": report.current_decision,
                    "past_policy": report.past_policy,
                    "current_policy": report.current_policy,
                    "confidence_shift": report.confidence_shift,
                    "reason": report.reason,
                    "recorded_at": report.timestamp,
                })
            log.info(f"Persisted {len(reports)} replay results to database")
            return True
        except Exception as e:
            log.error(f"Failed to persist results to database: {e}")
            return False

    def _persist_to_local(self, reports: List[DivergenceReport]) -> bool:
        """Persist reports to local JSON file."""
        try:
            filename = f"/tmp/replay_results_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
            data = {
                "timestamp": datetime.utcnow().isoformat(),
                "stats": {
                    "total_replayed": self.stats["total_replayed"],
                    "divergences_found": self.stats["divergences_found"],
                    "no_change": self.stats["no_change"],
                    "policies_changed": list(self.stats["policies_changed"]),
                },
                "reports": [asdict(r) for r in reports],
            }
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
            log.info(f"Persisted {len(reports)} replay results to {filename}")
            return True
        except Exception as e:
            log.error(f"Failed to persist results locally: {e}")
            return False

    def get_summary(self) -> Dict[str, Any]:
        """Return summary statistics of replay results."""
        return {
            "total_replayed": self.stats["total_replayed"],
            "divergences_found": self.stats["divergences_found"],
            "no_change": self.stats["no_change"],
            "divergence_rate": (
                self.stats["divergences_found"] / max(self.stats["total_replayed"], 1) * 100
            ),
            "policies_with_changes": list(self.stats["policies_changed"]),
        }

    def get_divergences(self) -> List[DivergenceReport]:
        """Return all divergence reports."""
        return [r for r in self.divergence_reports if r.diverged]

    def print_report(self):
        """Print human-readable replay report."""
        summary = self.get_summary()
        print("\n=== Counterfactual Replay Report ===")
        print(f"Total replayed: {summary['total_replayed']}")
        print(f"Divergences found: {summary['divergences_found']}")
        print(f"No change: {summary['no_change']}")
        print(f"Divergence rate: {summary['divergence_rate']:.1f}%")
        print(f"Policies with changes: {', '.join(summary['policies_with_changes']) or 'none'}")

        if self.divergence_reports:
            print("\n=== Divergence Details ===")
            for report in self.divergence_reports:
                if report.diverged:
                    print(f"  Task {report.task_id}: {report.past_decision} → {report.current_decision}")
                    print(f"    Policy: {report.past_policy} → {report.current_policy}")
                    print(f"    Reason: {report.reason}")
