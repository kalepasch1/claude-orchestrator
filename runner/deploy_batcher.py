"""
deploy_batcher.py — Dev-to-prod batch management for the Trojun Orchestrator Terminal.

Manages the lifecycle of deployment batches from QUEUED → COLLECTING → READY →
DEPLOYING → DEPLOYED → TESTING → APPROVED → PROMOTING → PRODUCTION.

Integrates with the existing db.py module for Supabase persistence.
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

log = logging.getLogger(__name__)


class BatchState(str, Enum):
    QUEUED = "QUEUED"
    COLLECTING = "COLLECTING"
    READY = "READY"
    DEPLOYING = "DEPLOYING"
    DEPLOYED = "DEPLOYED"
    TESTING = "TESTING"
    APPROVED = "APPROVED"
    PROMOTING = "PROMOTING"
    PRODUCTION = "PRODUCTION"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class DeployBatch:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    state: BatchState = BatchState.QUEUED
    task_slugs: list[str] = field(default_factory=list)
    target_env: str = "dev"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    deployed_at: Optional[str] = None
    promoted_at: Optional[str] = None
    error: Optional[str] = None
    window_seconds: int = 900
    max_tasks: int = 10

    def to_dict(self) -> dict:
        d = asdict(self)
        d['state'] = self.state.value
        return d

    def transition(self, new_state: BatchState) -> None:
        log.info("Batch %s: %s → %s", self.id, self.state.value, new_state.value)
        self.state = new_state
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def add_task(self, slug: str) -> bool:
        if len(self.task_slugs) >= self.max_tasks:
            return False
        if slug not in self.task_slugs:
            self.task_slugs.append(slug)
        return True

    @property
    def is_full(self) -> bool:
        return len(self.task_slugs) >= self.max_tasks


class DeployBatchManager:
    """Simple in-process batch manager. For multi-process use, persist to Supabase."""

    def __init__(self, window_seconds: int = 900, max_tasks: int = 10):
        self._batches: dict[str, DeployBatch] = {}
        self._active_dev: Optional[str] = None
        self.window_seconds = window_seconds
        self.max_tasks = max_tasks

    def get_or_create_dev_batch(self) -> DeployBatch:
        if self._active_dev and self._active_dev in self._batches:
            batch = self._batches[self._active_dev]
            if batch.state == BatchState.COLLECTING and not batch.is_full:
                return batch

        batch = DeployBatch(
            window_seconds=self.window_seconds,
            max_tasks=self.max_tasks,
        )
        batch.transition(BatchState.COLLECTING)
        self._batches[batch.id] = batch
        self._active_dev = batch.id
        return batch

    def add_task_to_batch(self, slug: str) -> str:
        batch = self.get_or_create_dev_batch()
        batch.add_task(slug)
        return batch.id

    def ready_batch(self, batch_id: str) -> bool:
        batch = self._batches.get(batch_id)
        if not batch or batch.state != BatchState.COLLECTING:
            return False
        batch.transition(BatchState.READY)
        return True

    def deploy_batch(self, batch_id: str, target: str = "dev") -> bool:
        batch = self._batches.get(batch_id)
        if not batch or batch.state not in (BatchState.READY, BatchState.QUEUED):
            return False
        batch.target_env = target
        batch.transition(BatchState.DEPLOYING)
        batch.deployed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        batch.transition(BatchState.DEPLOYED)
        return True

    def approve_batch(self, batch_id: str) -> bool:
        batch = self._batches.get(batch_id)
        if not batch or batch.state not in (BatchState.DEPLOYED, BatchState.TESTING):
            return False
        batch.transition(BatchState.APPROVED)
        return True

    def promote_batch(self, batch_id: str) -> bool:
        batch = self._batches.get(batch_id)
        if not batch or batch.state != BatchState.APPROVED:
            return False
        batch.transition(BatchState.PROMOTING)
        batch.promoted_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        batch.transition(BatchState.PRODUCTION)
        return True

    def get_batch(self, batch_id: str) -> Optional[dict]:
        batch = self._batches.get(batch_id)
        return batch.to_dict() if batch else None

    def list_batches(self, limit: int = 20) -> list[dict]:
        batches = sorted(self._batches.values(), key=lambda b: b.created_at, reverse=True)
        return [b.to_dict() for b in batches[:limit]]

    def stats(self) -> dict:
        all_b = list(self._batches.values())
        return {
            "total": len(all_b),
            "collecting": sum(1 for b in all_b if b.state == BatchState.COLLECTING),
            "ready": sum(1 for b in all_b if b.state == BatchState.READY),
            "deployed": sum(1 for b in all_b if b.state == BatchState.DEPLOYED),
            "production": sum(1 for b in all_b if b.state == BatchState.PRODUCTION),
            "failed": sum(1 for b in all_b if b.state == BatchState.FAILED),
        }


# Module-level singleton
_manager: Optional[DeployBatchManager] = None


def get_manager() -> DeployBatchManager:
    global _manager
    if _manager is None:
        window = int(os.environ.get("DEPLOY_BATCH_WINDOW", "900"))
        max_b = int(os.environ.get("DEPLOY_MAX_BATCH", "10"))
        _manager = DeployBatchManager(window_seconds=window, max_tasks=max_b)
    return _manager
