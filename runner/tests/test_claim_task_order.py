"""
claim_task ordering tests. DB access is fully mocked.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


class TestClaimTaskOrder(unittest.TestCase):
    def setUp(self):
        self.orig = (db.select, db._req)
        self.claimed = []

    def tearDown(self):
        db.select, db._req = self.orig

    def test_controls_ev_ranking_is_consumed_when_task_priority_absent(self):
        tasks = [
            {"id": "slow", "project_id": "p1", "slug": "slow", "deps": [], "created_at": "2026-01-01"},
            {"id": "fast", "project_id": "p1", "slug": "fast", "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.ev_ranking":
                    return [{"value": '["fast", "slow"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state == "in.(RUNNING,RETRY)":
                    return []
                if state == "in.(RUNNING,DONE,MERGED)":
                    return []
                if state == "in.(DONE,MERGED)":
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "fast")
        self.assertEqual(self.claimed, ["fast"])

    def test_confidence_fallback_orders_when_no_ev_row(self):
        tasks = [
            {"id": "low", "project_id": "p1", "slug": "low", "deps": [], "confidence": 0.1, "created_at": "2026-01-01"},
            {"id": "high", "project_id": "p1", "slug": "high", "deps": [], "confidence": 0.9, "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "high")

    def test_owner_project_priority_beats_fifo_and_thermal_noise(self):
        tasks = [
            {"id": "barks-old", "project_id": "p-barks", "slug": "barks-old", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "tomorrow-new", "project_id": "p-tomorrow", "slug": "tomorrow-new", "deps": [],
             "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [
                    {"id": "p-barks", "name": "sustainable-barks", "priority": 1, "concurrency_weight": 99},
                    {"id": "p-tomorrow", "name": "tomorrow", "priority": 9, "concurrency_weight": 1},
                ]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["barks-old", "tomorrow-new"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "tomorrow-new")

    def test_recovery_backlog_jumps_ahead_of_net_new_thermal_rank(self):
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-feature", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-old-work",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["new", "recover"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RECOVERY_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "recover")
        self.assertEqual(self.claimed, ["recover"])

    def test_recovery_jump_can_be_disabled_for_old_ordering(self):
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-feature", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-old-work",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["new", "recover"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RECOVERY_JUMP_QUEUE": "false"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "new")

    def test_improvement_backlog_jumps_ahead_after_recovery_is_gone(self):
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-feature", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "improve", "project_id": "p1", "slug": "improve-autonomous-queue-health",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["new", "improve"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_IMPROVEMENT_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "improve")

    def test_canary_evidence_jumps_ahead_of_improvement_and_net_new(self):
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-feature", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "improve", "project_id": "p1", "slug": "improve-autonomous-queue-health",
             "deps": [], "created_at": "2026-01-02"},
            {"id": "canary", "project_id": "p1", "slug": "canary-ollama-1",
             "deps": [], "created_at": "2026-01-03", "note": "coder-canary: routing sample"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["new", "improve", "canary"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_EVIDENCE_JUMP_QUEUE": "true",
                                     "ORCH_IMPROVEMENT_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "canary")

    def test_recovery_still_beats_improvement_work(self):
        tasks = [
            {"id": "improve", "project_id": "p1", "slug": "improve-autonomous-queue-health",
             "deps": [], "created_at": "2026-01-01"},
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-old-work",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["improve", "recover"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "recover")

    def test_canary_evidence_beats_recovery_to_unblock_router_learning(self):
        tasks = [
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-old-work",
             "deps": [], "created_at": "2026-01-01"},
            {"id": "canary", "project_id": "p1", "slug": "recover-missing-branch-canary-gemini-1",
             "kind": "canary", "deps": [], "created_at": "2026-01-02",
             "note": "coder-canary: historical merged-task routing sample"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_EVIDENCE_JUMP_QUEUE": "true",
                                     "ORCH_RECOVERY_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "canary")

    def test_release_fix_beats_recovery_for_deploy_readiness(self):
        tasks = [
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-old-work",
             "deps": [], "created_at": "2026-01-01"},
            {"id": "relfix", "project_id": "p1", "slug": "relfix-app-07070200",
             "deps": [], "created_at": "2026-01-02", "note": "auto-queued by release_train build-red self-heal"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
                                     "ORCH_RECOVERY_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "relfix")

    def test_evidence_reserved_lane_can_beat_release_fix_once(self):
        tasks = [
            {"id": "canary", "project_id": "p1", "slug": "canary-gemini-1",
             "kind": "canary", "deps": [], "created_at": "2026-01-01",
             "note": "coder-canary: historical merged-task routing sample"},
            {"id": "relfix", "project_id": "p1", "slug": "relfix-app-07070200",
             "deps": [], "created_at": "2026-01-02", "note": "auto-queued by release_train build-red self-heal"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_EVIDENCE_RESERVED_LANES": "1",
                                     "ORCH_RELEASE_FIX_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "canary")

    def test_release_fix_wins_when_evidence_lane_is_already_active(self):
        tasks = [
            {"id": "canary", "project_id": "p1", "slug": "canary-gemini-1",
             "kind": "canary", "deps": [], "created_at": "2026-01-01",
             "note": "coder-canary: historical merged-task routing sample"},
            {"id": "relfix", "project_id": "p1", "slug": "relfix-app-07070200",
             "deps": [], "created_at": "2026-01-02", "note": "auto-queued by release_train build-red self-heal"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state == "in.(RUNNING,RETRY)":
                    return [{"project_id": "p1", "slug": "canary-gpt-1", "kind": "canary",
                             "note": "coder-canary: running"}]
                if state in ("in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_EVIDENCE_RESERVED_LANES": "1",
                                     "ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
                                     "ORCH_EVIDENCE_PER_PROJECT_CODE_LANES": "2"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "relfix")

    def test_recovery_can_use_priority_lane_when_project_cap_is_full(self):
        tasks = [
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-old-work",
             "deps": [], "created_at": "2026-01-01"},
            {"id": "new", "project_id": "p2", "slug": "net-new-feature",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [
                    {"id": "p1", "name": "app1", "priority": 5, "concurrency_weight": 1},
                    {"id": "p2", "name": "app2", "priority": 5, "concurrency_weight": 1},
                ]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state == "in.(RUNNING,RETRY)":
                    return [{"project_id": "p1"}]
                if state in ("in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_PER_PROJECT_CODE_LANES": "1",
                                     "ORCH_RECOVERY_PER_PROJECT_CODE_LANES": "2"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "recover")

    def test_release_fix_beats_higher_portfolio_project_net_new_work(self):
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-tomorrow", "deps": [],
             "created_at": "2026-01-01", "kind": "feature"},
            {"id": "qafix", "project_id": "p2", "slug": "qafix-racefeed-a1b2c3d4e5f6", "deps": [],
             "created_at": "2026-01-02", "kind": "bugfix"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [
                    {"id": "p1", "name": "tomorrow", "priority": 1, "concurrency_weight": 1},
                    {"id": "p2", "name": "racefeed", "priority": 9, "concurrency_weight": 1},
                ]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state == "eq.QUEUED": return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"): return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
                                     "ORCH_EVIDENCE_RESERVED_LANES": "0"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "qafix")

    def test_exact_signature_release_fix_beats_legacy_higher_portfolio_fix(self):
        tasks = [
            {"id": "legacy", "project_id": "p1", "slug": "qafix-tomorrow-old-slice-4", "deps": [],
             "created_at": "2026-01-01", "kind": "bugfix"},
            {"id": "exact", "project_id": "p2", "slug": "qafix-racefeed-a1b2c3d4e5f6", "deps": [],
             "created_at": "2026-01-02", "kind": "bugfix"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "tomorrow", "priority": 1, "concurrency_weight": 1},
                        {"id": "p2", "name": "racefeed", "priority": 9, "concurrency_weight": 1}]
            if table == "controls": return []
            if table == "tasks":
                if params.get("state") == "eq.QUEUED": return [dict(t) for t in tasks]
                return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
                                     "ORCH_EVIDENCE_RESERVED_LANES": "0"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "exact")

    def test_new_release_fix_escapes_oldest_first_scan_cap(self):
        legacy = {"id": "old", "project_id": "p1", "slug": "old-feature", "deps": [],
                  "created_at": "2025-01-01", "kind": "feature"}
        exact = {"id": "exact", "project_id": "p1", "slug": "qafix-app-a1b2c3d4e5f6", "deps": [],
                 "created_at": "2026-07-14", "kind": "bugfix"}

        def select(table, params=None):
            params = params or {}
            if table == "projects": return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls": return []
            if table == "tasks":
                if params.get("state") == "eq.QUEUED":
                    return [dict(exact)] if "qafix" in params.get("or", "") else ([dict(legacy)] if not params.get("or") else [])
                return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [exact if task_id == "exact" else legacy]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
                                     "ORCH_EVIDENCE_RESERVED_LANES": "0"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "exact")

    def test_toolchain_repair_escapes_oldest_first_scan_cap(self):
        legacy = {"id": "old", "project_id": "p1", "slug": "old-feature", "deps": [],
                  "created_at": "2025-01-01", "kind": "feature"}
        repair = {"id": "repair", "project_id": "p1", "slug": "toolchain-repair-p1", "deps": [],
                  "created_at": "2026-07-14", "kind": "bugfix"}

        def select(table, params=None):
            params = params or {}
            if table == "projects": return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls": return []
            if table == "tasks" and params.get("state") == "eq.QUEUED":
                return [dict(repair)] if "toolchain-repair" in params.get("or", "") else ([dict(legacy)] if not params.get("or") else [])
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [repair if task_id == "repair" else legacy]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
                                     "ORCH_EVIDENCE_RESERVED_LANES": "0"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "repair")

    def test_ordinary_work_still_respects_project_cap(self):
        tasks = [
            {"id": "blocked-by-cap", "project_id": "p1", "slug": "net-new-p1",
             "deps": [], "created_at": "2026-01-01"},
            {"id": "other-project", "project_id": "p2", "slug": "net-new-p2",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [
                    {"id": "p1", "name": "app1", "priority": 5, "concurrency_weight": 1},
                    {"id": "p2", "name": "app2", "priority": 5, "concurrency_weight": 1},
                ]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state in ("eq.QUEUED", "in.(QUEUED,TESTING)"):
                    return [dict(t) for t in tasks]
                if state == "in.(RUNNING,RETRY)":
                    return [{"project_id": "p1"}]
                if state in ("in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_PER_PROJECT_CODE_LANES": "1"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "other-project")

    def test_rework_backlog_jumps_ahead_of_net_new_thermal_rank(self):
        """STARVATION FIX regression test: rework-* tasks (blocker_quarantine's legal/secret/
        security replacements) matched no jump-queue category, so a task like this sat QUEUED
        for 2+ days at attempt=0 while an always-present recovery/release-fix backlog kept
        winning every tie-break. rework_rank gives it a bounded jump-queue tier of its own."""
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-feature", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "rework", "project_id": "p1", "slug": "rework-secret-old-work",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                if params.get("key") == "eq.thermal_ranking":
                    return [{"value": '["new", "rework"]'}]
                return []
            if table == "tasks":
                state = params.get("state")
                if state == "eq.QUEUED":
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_QUARANTINE_REWORK_JUMP_QUEUE": "true"}, clear=False):
            task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "rework")
        self.assertEqual(self.claimed, ["rework"])

    def test_recovery_still_beats_rework_when_both_present(self):
        """Recovery is 'already mostly solved work' (existing comment); rework needs a fresh
        agent run. Recovery should keep winning the tie-break over rework when both backlogs
        exist simultaneously."""
        tasks = [
            {"id": "rework", "project_id": "p1", "slug": "rework-secret-old-work",
             "deps": [], "created_at": "2026-01-01"},
            {"id": "recover", "project_id": "p1", "slug": "recover-missing-branch-x",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state == "eq.QUEUED":
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        task = db.claim_task("runner-1")
        self.assertEqual(task["id"], "recover")

    def test_rework_jump_can_be_disabled(self):
        tasks = [
            {"id": "new", "project_id": "p1", "slug": "net-new-feature", "deps": [],
             "created_at": "2026-01-01"},
            {"id": "rework", "project_id": "p1", "slug": "rework-secret-old-work",
             "deps": [], "created_at": "2026-01-02"},
        ]

        def select(table, params=None):
            params = params or {}
            if table == "projects":
                return [{"id": "p1", "name": "app", "priority": 5, "concurrency_weight": 1}]
            if table == "controls":
                return []
            if table == "tasks":
                state = params.get("state")
                if state == "eq.QUEUED":
                    return [dict(t) for t in tasks]
                if state in ("in.(RUNNING,RETRY)", "in.(RUNNING,DONE,MERGED)", "in.(DONE,MERGED)"):
                    return []
            return []

        def req(method, path, body=None, headers=None, params=None):
            task_id = params.get("id", "").replace("eq.", "")
            self.claimed.append(task_id)
            return [next(t for t in tasks if t["id"] == task_id)]

        db.select = select
        db._req = req
        with patch.dict(os.environ, {"ORCH_QUARANTINE_REWORK_JUMP_QUEUE": "false"}, clear=False):
            task = db.claim_task("runner-1")
        # oldest-first (created_at) with no jump-queue tier active
        self.assertEqual(task["id"], "new")


if __name__ == "__main__":
    unittest.main(verbosity=2)
