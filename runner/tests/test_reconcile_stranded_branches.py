"""Tests for reconcile_stranded_branches — the branch-driven stranded-work recovery.

The invariants that matter here are safety invariants, not happy-path ones:
  - a conflicting branch is NEVER carded,
  - an unclassifiable branch is NEVER carded (fail closed),
  - a branch that already has a card is NEVER carded twice,
  - report mode writes nothing,
  - nothing is ever written to `tasks`.
"""
import os
import sys
import types
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

# db and merge_train reach the network on import in some builds; stub anything missing
# so the test file is importable in a bare checkout.
for _name in ("db", "merge_train"):
    if _name not in sys.modules:
        try:
            __import__(_name)
        except Exception:  # pragma: no cover - environment dependent
            sys.modules[_name] = types.ModuleType(_name)

import reconcile_stranded_branches as rsb  # noqa: E402


class ListBranchesTest(unittest.TestCase):
    def test_parses_ls_remote_heads(self):
        out = ("aaa111\trefs/heads/agent/foo\n"
               "bbb222\trefs/heads/agent/bar\n"
               "ccc333\trefs/heads/master\n")
        with mock.patch.object(rsb, "_git", return_value=(0, out)), \
             mock.patch.object(os.path, "isdir", return_value=True):
            heads = rsb.list_agent_branches("/repo")
        self.assertEqual(heads, {"agent/foo": "aaa111", "agent/bar": "bbb222",
                                 "master": "ccc333"})

    def test_missing_repo_returns_empty(self):
        self.assertEqual(rsb.list_agent_branches("/definitely/not/here"), {})

    def test_git_failure_returns_empty(self):
        with mock.patch.object(rsb, "_git", return_value=(128, "")), \
             mock.patch.object(os.path, "isdir", return_value=True):
            self.assertEqual(rsb.list_agent_branches("/repo"), {})


class ClassifyTest(unittest.TestCase):
    def test_ancestor_is_merged(self):
        with mock.patch.object(rsb, "_git", return_value=(0, "")):
            self.assertEqual(rsb.classify_branch("/repo", "sha", "base"), rsb.MERGED)

    def test_clean_merge(self):
        calls = [(1, ""), (0, "")]  # not-ancestor, then merge-tree ok
        with mock.patch.object(rsb, "_git", side_effect=calls):
            self.assertEqual(rsb.classify_branch("/repo", "sha", "base"), rsb.CLEAN)

    def test_conflicting_merge(self):
        calls = [(1, ""), (1, "conflict")]  # not-ancestor, merge-tree rc=1
        with mock.patch.object(rsb, "_git", side_effect=calls):
            self.assertEqual(rsb.classify_branch("/repo", "sha", "base"),
                             rsb.CONFLICTING)

    def test_legacy_git_fallback_detects_conflict_markers(self):
        calls = [(1, ""), (129, ""), (0, "some\n<<<<<<< ours\n")]
        with mock.patch.object(rsb, "_git", side_effect=calls):
            self.assertEqual(rsb.classify_branch("/repo", "sha", "base"),
                             rsb.CONFLICTING)

    def test_legacy_git_fallback_clean(self):
        calls = [(1, ""), (129, ""), (0, "no markers here")]
        with mock.patch.object(rsb, "_git", side_effect=calls):
            self.assertEqual(rsb.classify_branch("/repo", "sha", "base"), rsb.CLEAN)

    def test_unreadable_is_unknown(self):
        calls = [(1, ""), (129, ""), (1, "")]
        with mock.patch.object(rsb, "_git", side_effect=calls):
            self.assertEqual(rsb.classify_branch("/repo", "sha", "base"), rsb.UNKNOWN)

    def test_missing_sha_is_unknown(self):
        self.assertEqual(rsb.classify_branch("/repo", "", "base"), rsb.UNKNOWN)
        self.assertEqual(rsb.classify_branch("/repo", "sha", ""), rsb.UNKNOWN)


class SlugTest(unittest.TestCase):
    def test_strips_prefix(self):
        self.assertEqual(rsb.slug_for_branch("agent/my-task"), "my-task")

    def test_leaves_unprefixed_alone(self):
        self.assertEqual(rsb.slug_for_branch("hotfix/x"), "hotfix/x")


class StrandedSelectionTest(unittest.TestCase):
    def test_only_clean_and_uncarded_are_stranded(self):
        inv = {"branches": [
            {"status": rsb.CLEAN, "has_card": False, "slug": "a"},
            {"status": rsb.CLEAN, "has_card": True, "slug": "b"},
            {"status": rsb.CONFLICTING, "has_card": False, "slug": "c"},
            {"status": rsb.MERGED, "has_card": False, "slug": "d"},
            {"status": rsb.UNKNOWN, "has_card": False, "slug": "e"},
        ]}
        self.assertEqual([b["slug"] for b in rsb.stranded_from(inv)], ["a"])

    def test_empty_inventory(self):
        self.assertEqual(rsb.stranded_from({}), [])


class InventoryTest(unittest.TestCase):
    def _inventory(self, heads, statuses, card_lookup):
        proj = {"name": "p", "repo_path": "/repo", "default_base": "master"}
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(rsb, "_base_sha", return_value="basesha"), \
             mock.patch.object(rsb, "list_agent_branches", return_value=heads), \
             mock.patch.object(rsb, "classify_branch",
                               side_effect=lambda r, s, b: statuses[s]), \
             mock.patch.object(rsb.merge_train, "_find_existing_card",
                               side_effect=card_lookup, create=True):
            return rsb.inventory(proj)

    def test_counts_and_card_lookup(self):
        inv = self._inventory(
            {"agent/a": "s1", "agent/b": "s2", "agent/c": "s3"},
            {"s1": rsb.CLEAN, "s2": rsb.CONFLICTING, "s3": rsb.MERGED},
            lambda slug: None)
        self.assertEqual(inv["total"], 3)
        self.assertEqual(inv["clean"], 1)
        self.assertEqual(inv["conflicting"], 1)
        self.assertEqual(inv["merged"], 1)
        self.assertEqual([b["slug"] for b in rsb.stranded_from(inv)], ["a"])

    def test_card_lookup_failure_fails_closed(self):
        def boom(_slug):
            raise RuntimeError("db down")
        inv = self._inventory({"agent/a": "s1"}, {"s1": rsb.CLEAN}, boom)
        # unreachable DB must NOT produce a queue-it decision
        self.assertEqual(rsb.stranded_from(inv), [])

    def test_missing_repo_path_yields_nothing(self):
        inv = rsb.inventory({"name": "p", "repo_path": None})
        self.assertEqual(inv["total"], 0)
        self.assertEqual(inv["branches"], [])


class RunTest(unittest.TestCase):
    BRANCHES = [{"branch": "agent/a", "sha": "s" * 40, "status": rsb.CLEAN,
                 "slug": "a", "has_card": False}]

    def _run(self, apply, find_card=lambda s: None, ensure=None, ensure_calls=None):
        inv = {"project": "p", "repo_path": "/repo", "base": "master", "total": 1,
               "merged": 0, "clean": 1, "conflicting": 0, "unknown": 0,
               "branches": list(self.BRANCHES)}

        def _ensure(*a, **kw):
            if ensure_calls is not None:
                ensure_calls.append((a, kw))
            return ensure if ensure is not None else "created"

        with mock.patch.object(rsb.db, "select",
                               return_value=[{"name": "p", "repo_path": "/repo"}],
                               create=True), \
             mock.patch.object(rsb, "inventory", return_value=inv), \
             mock.patch.object(rsb, "_load_checkpoint", return_value=set()), \
             mock.patch.object(rsb, "_save_checkpoint"), \
             mock.patch.object(rsb.merge_train, "CARD_OK", ("created", "exists"),
                               create=True), \
             mock.patch.object(rsb.merge_train, "_find_existing_card",
                               side_effect=find_card, create=True), \
             mock.patch.object(rsb.merge_train, "ensure_integration_card_result",
                               side_effect=_ensure, create=True):
            return rsb.run(apply=apply)

    def test_report_mode_writes_nothing(self):
        calls = []
        totals = self._run(apply=False, ensure_calls=calls)
        self.assertEqual(calls, [])
        self.assertFalse(totals["applied"])
        self.assertEqual(totals["filed"], 1)  # counted as "would file"

    def test_apply_files_card(self):
        calls = []
        totals = self._run(apply=True, ensure_calls=calls)
        self.assertEqual(len(calls), 1)
        self.assertEqual(totals["filed"], 1)
        self.assertEqual(totals["failed"], 0)
        kwargs = calls[0][1]
        self.assertEqual(kwargs["status"], "approved")
        self.assertIn("reconcile-stranded-branches", kwargs["decided_by"])

    def test_idempotent_when_card_appears_between_scan_and_write(self):
        calls = []
        totals = self._run(apply=True, find_card=lambda s: {"id": "x"},
                           ensure_calls=calls)
        self.assertEqual(calls, [])          # never wrote
        self.assertEqual(totals["filed"], 0)
        self.assertEqual(totals["failed"], 0)

    def test_card_write_failure_is_counted_not_raised(self):
        totals = self._run(apply=True, ensure="rejected")
        self.assertEqual(totals["filed"], 0)
        self.assertEqual(totals["failed"], 1)

    def test_no_matching_project_is_a_noop(self):
        with mock.patch.object(rsb.db, "select", return_value=[], create=True):
            totals = rsb.run(project_name="nope")
        self.assertEqual(totals["stranded"], 0)
        self.assertEqual(totals["filed"], 0)


class ReadOnlyAgainstTasksTest(unittest.TestCase):
    def test_module_never_updates_tasks(self):
        src = open(rsb.__file__).read()
        for forbidden in ('db.update', 'db.insert("tasks"', "db.insert('tasks'",
                          '"tasks"', "'tasks'"):
            self.assertNotIn(forbidden, src.split('"""', 2)[2],
                             f"{forbidden} must not appear outside the docstring")


if __name__ == "__main__":
    unittest.main()
