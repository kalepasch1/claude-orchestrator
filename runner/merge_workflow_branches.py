"""Wire branch creation into merge approval workflow.

When an MR is approved, detects missing branches, deduplicates,
and queues branch-creation tasks.
"""

import logging
from typing import Dict, List, Any, Set, Optional, Callable

log = logging.getLogger(__name__)


class BranchCreationTask:
    """A queued branch-creation task."""

    def __init__(self, project_id: str, branch_name: str,
                 base_branch: str = "main", source_mr_id: str = ""):
        self.project_id = project_id
        self.branch_name = branch_name
        self.base_branch = base_branch
        self.source_mr_id = source_mr_id
        self.status = "pending"
        self.result: Optional[str] = None


class MergeWorkflowBranchManager:
    """Manages branch creation as part of the merge workflow."""

    def __init__(self,
                 detect_missing_fn: Optional[Callable] = None,
                 create_branch_fn: Optional[Callable] = None):
        self._detect_missing_fn = detect_missing_fn
        self._create_branch_fn = create_branch_fn
        self._queued_tasks: List[BranchCreationTask] = []
        self._created_branches: Set[str] = set()

    def on_mr_approved(self, mr: Dict[str, Any]) -> List[BranchCreationTask]:
        """Handle MR approval: detect missing branches, dedup, queue.

        Args:
            mr: Dict with project_id, mr_id, target_branches, base_branch
        """
        project_id = mr.get("project_id", "")
        mr_id = mr.get("mr_id", "")
        target_branches = mr.get("target_branches", [])
        base_branch = mr.get("base_branch", "main")

        # 1. Detect missing branches
        if self._detect_missing_fn:
            try:
                missing = self._detect_missing_fn(project_id, target_branches)
            except Exception as e:
                log.error("Branch detection failed for MR %s: %s", mr_id, e)
                missing = []
        else:
            # Without detection, treat all targets as potentially missing
            missing = target_branches

        # 2. Deduplicate against already-created and already-queued
        queued_names = {t.branch_name for t in self._queued_tasks if t.status == "pending"}
        new_tasks = []

        for branch_name in missing:
            if branch_name in self._created_branches:
                log.info("Branch %s already created, skipping", branch_name)
                continue
            if branch_name in queued_names:
                log.info("Branch %s already queued, skipping", branch_name)
                continue

            task = BranchCreationTask(
                project_id=project_id,
                branch_name=branch_name,
                base_branch=base_branch,
                source_mr_id=mr_id,
            )
            self._queued_tasks.append(task)
            queued_names.add(branch_name)
            new_tasks.append(task)

        log.info("MR %s: queued %d branch creation tasks", mr_id, len(new_tasks))
        return new_tasks

    def execute_pending(self) -> List[BranchCreationTask]:
        """Execute all pending branch-creation tasks."""
        executed = []
        for task in self._queued_tasks:
            if task.status != "pending":
                continue

            if self._create_branch_fn is None:
                task.status = "failed"
                task.result = "no create_branch function"
                executed.append(task)
                continue

            try:
                result = self._create_branch_fn(
                    task.project_id, task.branch_name, task.base_branch
                )
                if hasattr(result, 'success') and result.success:
                    task.status = "completed"
                    task.result = getattr(result, 'reason', 'ok')
                    self._created_branches.add(task.branch_name)
                elif isinstance(result, bool) and result:
                    task.status = "completed"
                    task.result = "ok"
                    self._created_branches.add(task.branch_name)
                else:
                    task.status = "failed"
                    task.result = getattr(result, 'reason', str(result))
            except Exception as e:
                task.status = "failed"
                task.result = str(e)

            executed.append(task)

        return executed

    @property
    def pending_count(self) -> int:
        return sum(1 for t in self._queued_tasks if t.status == "pending")

    @property
    def created_branches(self) -> Set[str]:
        return set(self._created_branches)

    def get_queue_state(self) -> Dict[str, Any]:
        """Return queue state summary."""
        by_status = {}
        for t in self._queued_tasks:
            by_status[t.status] = by_status.get(t.status, 0) + 1
        return {
            "total": len(self._queued_tasks),
            "by_status": by_status,
            "created_branches": list(self._created_branches),
        }
