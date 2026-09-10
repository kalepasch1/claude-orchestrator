"""Main orchestrator: coordinates task routing and decision replay.

Integrates:
- Policy-based task routing
- Periodic counterfactual replay for divergence detection
- Results persistence for optimization
"""

import logging
import os
from typing import Dict, List, Any, Optional

from src.orchestrator.runners.replay_runner import ReplayRunner
from src.orchestrator.policies import DefaultPolicy, AffinityPolicy

log = logging.getLogger(__name__)


class Orchestrator:
    """Main orchestration engine for task routing and policy optimization."""

    def __init__(self, db=None, enable_replay: bool = True):
        """Initialize orchestrator.

        Args:
            db: Database client for persistence (optional).
            enable_replay: Enable periodic counterfactual replay.
        """
        self.db = db
        self.enable_replay = enable_replay
        self.policies = [
            DefaultPolicy(),
            AffinityPolicy(),
        ]
        self.replay_runner = ReplayRunner(policies=self.policies, db=db) if enable_replay else None
        self._init_logging()

    def _init_logging(self):
        """Configure logging for orchestrator operations."""
        if not logging.getLogger("orchestrator").handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logging.getLogger("orchestrator").addHandler(handler)
            logging.getLogger("orchestrator").setLevel(
                os.environ.get("ORCH_LOG_LEVEL", "INFO")
            )

    def run_replay_analysis(self, limit: int = 10, days_back: int = 7) -> Dict[str, Any]:
        """Execute counterfactual replay of past decisions.

        Args:
            limit: Maximum number of past records to replay.
            days_back: Only replay records from the last N days.

        Returns:
            Dictionary with replay results and summary statistics.
        """
        if not self.enable_replay or not self.replay_runner:
            log.warning("Replay runner not enabled")
            return {"enabled": False}

        try:
            # Load historical task execution records
            loaded = self.replay_runner.load_history(limit=limit, days_back=days_back)
            if not loaded:
                log.warning("No historical records loaded for replay")
                return {"loaded": 0, "divergences": []}

            # Re-evaluate each record against current policies
            reports = self.replay_runner.run_replay()

            # Persist results for analysis
            self.replay_runner.persist_results(reports)

            # Return summary
            summary = self.replay_runner.get_summary()
            divergences = [
                {
                    "task_id": r.task_id,
                    "past": r.past_decision,
                    "current": r.current_decision,
                    "reason": r.reason,
                }
                for r in self.replay_runner.get_divergences()
            ]

            return {
                "enabled": True,
                "loaded": loaded,
                "summary": summary,
                "divergences": divergences,
            }
        except Exception as e:
            log.error(f"Replay analysis failed: {e}")
            return {"error": str(e)}

    def get_replay_summary(self) -> Dict[str, Any]:
        """Get summary of last replay run without executing new replay."""
        if not self.replay_runner:
            return {}
        return self.replay_runner.get_summary()

    def print_replay_report(self):
        """Print human-readable replay report to stdout."""
        if self.replay_runner:
            self.replay_runner.print_report()
        else:
            print("Replay runner not enabled")


def create_orchestrator(db=None, enable_replay: bool = True) -> Orchestrator:
    """Factory function to create orchestrator instance.

    Args:
        db: Database client (optional).
        enable_replay: Enable counterfactual replay.

    Returns:
        Initialized Orchestrator instance.
    """
    return Orchestrator(db=db, enable_replay=enable_replay)


if __name__ == "__main__":
    # Simple CLI for running replay manually
    import argparse
    parser = argparse.ArgumentParser(description="Run orchestrator replay analysis")
    parser.add_argument("--limit", type=int, default=10,
                       help="Maximum records to replay")
    parser.add_argument("--days", type=int, default=7,
                       help="Days back to search")
    parser.add_argument("--report", action="store_true",
                       help="Print human-readable report")
    args = parser.parse_args()

    orch = create_orchestrator()
    if args.report:
        orch.print_replay_report()
    else:
        result = orch.run_replay_analysis(limit=args.limit, days_back=args.days)
        import json
        print(json.dumps(result, indent=2))
