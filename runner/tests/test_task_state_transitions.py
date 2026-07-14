#!/usr/bin/env python3
"""
test_task_state_transitions.py - verify task state transition logic.

Covers:
  - Valid transitions: QUEUED->RUNNING, RUNNING->DONE, RUNNING->BLOCKED, BLOCKED->QUEUED
  - auto_remediate correctly transitions BLOCKED->QUEUED with escalation
  - No-op auto-closed DONE tasks are recovered to QUEUED
  - HARD_CAP shelving: tasks past the remediation hard cap get SHELVED or DECOMPOSED
  - Transient failures requeue without model escalation
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import auto_remediate
import agentic_repair


class TaskStateTransitionTest(unittest.TestCase):
    """Core state transition invariants."""

    def _make_task(self, state="BLOCKED", slug="test-task", note="", rc=0, model="claude-sonnet-4-6"):
        return {
            "id": f"id-{slug}",
            "slug": slug,
            "state": state,
            "prompt": f"Implement {slug}.",
            "note": note,
            "model": model,
            "remediation_count": rc,
            "material": False,
            "project_id": "proj-1",
            "base_branch": "main",
            "log_tail": "",
        }

    # --- BLOCKED -> QUEUED (transient) ---
    def test_transient_blocked_requeues_without_escalation(self):
        t = self._make_task(note="503 overload from provider")
        updates = {}
        db = MagicMock()
        db.select.return_value = [t]
        db.update.side_effect = lambda table, match, patch: updates.update(patch)

        with patch.object(auto_remediate, "db", db), \
             patch.object(auto_remediate, "recover_pending_manual_reviews", return_value=0), \
             patch.object(auto_remediate, "recover_auto_closed_noops", return_value=0), \
             patch.object(auto_remediate, "recover_shelved", return_value=(0, 0)), \
             patch.object(auto_remediate, "offload_budget_capacity_backlog", return_value=0):
            auto_remediate.run(limit=1)

        self.assertEqual(updates.get("state"), "QUEUED")
        self.assertGreaterEqual(updates.get("remediation_count", 0), 1)

    # --- BLOCKED -> QUEUED (no-op escalation) ---
    def test_noop_blocked_requeues_with_sharper_prompt(self):
        t = self._make_task(note="no committable changes produced", rc=0)
        updates = {}
        db = MagicMock()
        db.select.return_value = [t]
        db.update.side_effect = lambda table, match, patch: updates.update(patch)

        with patch.object(auto_remediate, "db", db), \
             patch.object(auto_remediate, "recover_pending_manual_reviews", return_value=0), \
             patch.object(auto_remediate, "recover_auto_closed_noops", return_value=0), \
             patch.object(auto_remediate, "recover_shelved", return_value=(0, 0)), \
             patch.object(auto_remediate, "offload_budget_capacity_backlog", return_value=0):
            auto_remediate.run(limit=1)

        self.assertEqual(updates.get("state"), "QUEUED")

    # --- HARD_CAP -> SHELVED/DECOMPOSED ---
    def test_hard_cap_shelves_atomic_task(self):
        t = self._make_task(note="agent run failed repeatedly", rc=auto_remediate.HARD_CAP)
        updates = {}
        db = MagicMock()
        db.select.return_value = [t]
        db.update.side_effect = lambda table, match, patch: updates.update(patch)

        with patch.object(auto_remediate, "db", db), \
