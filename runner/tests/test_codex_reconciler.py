"""Tests for codex_reconciler — Codex evidence classification + recovery ledger.

The reconcile contract has two hard requirements and one hard prohibition, and those are
what this file defends:

  ZERO UNKNOWN     classify_item is TOTAL. Every input, including malformed ones and ones
                   that make it raise, yields one of the five defined classifications.
  DURABLE LEDGER   one record per item, idempotent across re-runs.
  READ-ONLY        the evidence is never deleted, reset, cleaned, popped or moved.

ALREADY_PRESENT gets the most attention because it is the only verdict that discards work:
it must require positive proof, never absence of evidence.
"""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _DIR)

import codex_reconciler as cr  # noqa: E402

FP = "7db8cf82aff72a99f50c1f44a21f39d2038875c674a1d63584730da07690ac2f"


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        # default: commit unknown to the repo, nothing matches, no remote, no live tasks
        self.git = mock.patch.object(cr, "_git", return_value=(1, "")).start()
        self.addCleanup(mock.patch.stopall)

    def test_broken_metadata_is_conflicted(self):
        v = cr.classify_item({"kind": "broken_codex_git_worktree",
                              "error": "git metadata no longer resolves"}, "/repo")
        self.assertEqual(v["classification"], cr.CONFLICTED)

    def test_error_field_alone_is_enough_to_conflict(self):
        v = cr.classify_item({"kind": "dirty_worktree", "error": "unreadable"}, "/repo")
        self.assertEqual(v["classification"], cr.CONFLICTED)

    def test_ancestor_commit_on_a_clean_worktree_is_already_present(self):
        with mock.patch.object(cr, "_commit_exists", return_value=True), \
             mock.patch.object(cr, "_is_ancestor", return_value=True), \
             mock.patch.object(cr, "_uncommitted_paths", return_value=[]):
            v = cr.classify_item({"kind": "dirty_worktree", "head": "a" * 40}, "/repo")
        self.assertEqual(v["classification"], cr.ALREADY_PRESENT)

    def test_ancestor_commit_with_uncommitted_files_is_recoverable(self):
        # REGRESSION (2026-08-12). orchestrator-session-fabric-current was called
        # ALREADY_PRESENT on ancestry alone while holding 18 uncommitted files — 386 lines
        # of unshipped work reported as "nothing here". Ancestry proves the COMMIT landed;
        # it is not proof the DIRECTORY is empty.
        with mock.patch.object(cr, "_commit_exists", return_value=True), \
             mock.patch.object(cr, "_is_ancestor", return_value=True), \
             mock.patch.object(cr, "_uncommitted_paths",
                               return_value=["web/server/utils/fleetHealth.ts"]):
            v = cr.classify_item({"kind": "detached_codex_worktree", "head": "a" * 40},
                                 "/repo")
        self.assertEqual(v["classification"], cr.RECOVERABLE_VALUE)
        self.assertIn("uncommitted", v["evidence"])

    def test_uncommitted_paths_prefers_the_scanner_change_list(self):
        self.assertEqual(cr._uncommitted_paths({"changes": ["a.py", "b.py"]}),
                         ["a.py", "b.py"])

    def test_uncommitted_paths_falls_back_to_asking_the_worktree(self):
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(cr, "_git", return_value=(0, " M web/x.ts\nA  y.sql\n")):
            self.assertEqual(cr._uncommitted_paths({"path": "/w"}), ["web/x.ts", "y.sql"])

    def test_uncommitted_paths_on_a_missing_worktree_is_empty(self):
        self.assertEqual(cr._uncommitted_paths({"path": "/no/such/dir"}), [])

    def test_uncommitted_paths_on_git_failure_is_empty(self):
        with mock.patch.object(os.path, "isdir", return_value=True), \
             mock.patch.object(cr, "_git", return_value=(128, "")):
            self.assertEqual(cr._uncommitted_paths({"path": "/w"}), [])

    def test_unknown_commit_is_never_already_present(self):
        # A sha the repo has never seen proves nothing. Calling that ALREADY_PRESENT is how
        # real work gets silently dropped.
        with mock.patch.object(cr, "_commit_exists", return_value=False):
            v = cr.classify_item({"kind": "dirty_worktree", "head": "b" * 40,
                                  "changes": ["x.py"]}, "/repo")
        self.assertNotEqual(v["classification"], cr.ALREADY_PRESENT)

    def test_all_files_identical_is_already_present(self):
        with mock.patch.object(cr, "_files_match_default", return_value=True):
            v = cr.classify_item({"kind": "dirty_worktree",
                                  "changes": ["a.py", "b.py"]}, "/repo")
        self.assertEqual(v["classification"], cr.ALREADY_PRESENT)

    def test_partial_file_match_is_recoverable_not_present(self):
        with mock.patch.object(cr, "_files_match_default", return_value=False):
            v = cr.classify_item({"kind": "dirty_worktree",
                                  "changes": ["a.py", "b.py"]}, "/repo")
        self.assertEqual(v["classification"], cr.RECOVERABLE_VALUE)

    def test_live_task_takes_ownership(self):
        v = cr.classify_item({"kind": "dirty_worktree", "branch": "codex/thing"},
                             "/repo", live_slugs={"thing"})
        self.assertEqual(v["classification"], cr.ACTIVE_IN_ANOTHER_TASK)

    def test_agent_branch_on_origin_takes_ownership(self):
        v = cr.classify_item({"kind": "dirty_worktree", "branch": "codex/thing"},
                             "/repo", remote_heads={"agent/thing": "c" * 40})
        self.assertEqual(v["classification"], cr.ACTIVE_IN_ANOTHER_TASK)

    def test_newer_remote_branch_supersedes(self):
        v = cr.classify_item({"kind": "dirty_worktree", "branch": "codex/x",
                              "head": "a" * 40}, "/repo",
                             remote_heads={"codex/x": "d" * 40})
        self.assertEqual(v["classification"], cr.SUPERSEDED_BY_NEWER)

    def test_identical_remote_head_does_not_supersede_itself(self):
        same = "a" * 40
        v = cr.classify_item({"kind": "dirty_worktree", "branch": "codex/x",
                              "head": same, "changes": ["z.py"]}, "/repo",
                             remote_heads={"codex/x": same})
        self.assertNotEqual(v["classification"], cr.SUPERSEDED_BY_NEWER)

    def test_missing_artifact_is_conflicted(self):
        v = cr.classify_item({"kind": "codex_output_artifact",
                              "path": "/no/such/file.patch"}, "/repo")
        self.assertEqual(v["classification"], cr.CONFLICTED)

    def test_present_artifact_is_recoverable(self):
        with tempfile.NamedTemporaryFile(suffix=".patch") as fh:
            fh.write(b"diff --git a/x b/x\n")
            fh.flush()
            v = cr.classify_item({"kind": "codex_output_artifact", "path": fh.name},
                                 "/repo")
        self.assertEqual(v["classification"], cr.RECOVERABLE_VALUE)

    def test_unrepresented_work_is_recoverable(self):
        v = cr.classify_item({"kind": "dirty_worktree", "branch": "codex/new",
                              "changes": ["a.py"], "change_count": 1}, "/repo")
        self.assertEqual(v["classification"], cr.RECOVERABLE_VALUE)


class TotalityTest(unittest.TestCase):
    """Zero UNKNOWN is a completion requirement, so the classifier must be total."""

    def test_every_verdict_is_a_defined_classification(self):
        for item in ({}, {"kind": None}, {"kind": "weird_new_kind"},
                     {"kind": "dirty_worktree", "head": None, "changes": None},
                     {"kind": "artifact", "path": None},
                     {"branch": 123, "changes": "not-a-list"}):
            v = cr.classify_item(item, "/repo")
            self.assertIn(v["classification"], cr.CLASSIFICATIONS, item)

    def test_classifier_exception_becomes_conflicted_not_unknown(self):
        with mock.patch.object(cr, "_slug_candidates", side_effect=RuntimeError("boom")):
            v = cr.classify_item({"kind": "dirty_worktree"}, "/repo")
        self.assertEqual(v["classification"], cr.CONFLICTED)
        self.assertIn("classifier error", v["reason"])

    def test_every_classification_has_a_disposition(self):
        for c in cr.CLASSIFICATIONS:
            self.assertTrue(cr.disposition_for(c))
            self.assertNotEqual(cr.disposition_for(c), "review")


class ItemKeyTest(unittest.TestCase):
    def test_stable_across_calls(self):
        item = {"kind": "dirty_worktree", "path": "/p", "branch": "b"}
        self.assertEqual(cr.item_key(FP, item), cr.item_key(FP, item))

    def test_differs_per_item(self):
        a = {"kind": "dirty_worktree", "path": "/p1", "branch": "b"}
        b = {"kind": "dirty_worktree", "path": "/p2", "branch": "b"}
        self.assertNotEqual(cr.item_key(FP, a), cr.item_key(FP, b))

    def test_differs_per_fingerprint(self):
        item = {"kind": "k", "path": "/p", "branch": "b"}
        self.assertNotEqual(cr.item_key(FP, item), cr.item_key("other", item))


class ReconcileTest(unittest.TestCase):
    GROUPS = {"beethoven": [
        {"kind": "dirty_worktree", "path": "/w/a", "branch": "codex/a",
         "head": "a" * 40, "changes": ["x.py"], "change_count": 1},
        {"kind": "broken_codex_git_worktree", "path": "/w/b",
         "error": "git metadata no longer resolves"},
    ]}

    def _reconcile(self, apply=False, existing=None, write_ok=True, writes=None):
        def _write(record):
            if writes is not None:
                writes.append(record)
            return write_ok
        with mock.patch.object(cr, "enumerate_evidence", return_value=self.GROUPS), \
             mock.patch.object(cr, "_remote_branches", return_value={}), \
             mock.patch.object(cr, "_live_task_slugs", return_value=set()), \
             mock.patch.object(cr, "_existing_keys", return_value=existing or set()), \
             mock.patch.object(cr, "_commit_exists", return_value=False), \
             mock.patch.object(cr, "_files_match_default", return_value=False), \
             mock.patch.object(cr, "write_ledger_record", side_effect=_write):
            return cr.reconcile(FP, app="beethoven", repo="/repo", apply=apply)

    def test_report_mode_writes_nothing(self):
        writes = []
        res = self._reconcile(apply=False, writes=writes)
        self.assertEqual(writes, [])
        self.assertEqual(res["written"], 0)
        self.assertEqual(res["total"], 2)

    def test_zero_unknown_items(self):
        self.assertEqual(self._reconcile()["unknown"], 0)

    def test_apply_writes_one_record_per_item(self):
        writes = []
        res = self._reconcile(apply=True, writes=writes)
        self.assertEqual(len(writes), 2)
        self.assertEqual(res["written"], 2)

    def test_records_carry_the_audit_fingerprint(self):
        writes = []
        self._reconcile(apply=True, writes=writes)
        self.assertTrue(all(w["fingerprint"] == FP for w in writes))

    def test_records_carry_source_classification_and_disposition(self):
        writes = []
        self._reconcile(apply=True, writes=writes)
        for w in writes:
            self.assertIn("source", w)
            self.assertIn(w["classification"], cr.CLASSIFICATIONS)
            self.assertTrue(w["disposition"])
            self.assertIn("task", w)
            self.assertIn("branch", w)
            self.assertIn("commit", w)

    def test_rerun_is_idempotent(self):
        keys = {cr.item_key(FP, i) for i in self.GROUPS["beethoven"]}
        writes = []
        res = self._reconcile(apply=True, existing=keys, writes=writes)
        self.assertEqual(writes, [])
        self.assertEqual(res["skipped_existing"], 2)

    def test_write_failure_is_counted_not_raised(self):
        res = self._reconcile(apply=True, write_ok=False)
        self.assertEqual(res["write_failed"], 2)
        self.assertEqual(res["written"], 0)

    def test_counts_sum_to_total(self):
        res = self._reconcile()
        self.assertEqual(sum(res["counts"].values()), res["total"])

    def test_no_evidence_is_a_clean_empty_result(self):
        with mock.patch.object(cr, "enumerate_evidence", return_value={}), \
             mock.patch.object(cr, "_remote_branches", return_value={}), \
             mock.patch.object(cr, "_live_task_slugs", return_value=set()):
            res = cr.reconcile(FP, repo="/repo")
        self.assertEqual(res["total"], 0)
        self.assertEqual(res["unknown"], 0)


class FailSoftTest(unittest.TestCase):
    def test_unreachable_database_yields_no_live_slugs_not_a_crash(self):
        db = mock.MagicMock()
        db.select.side_effect = RuntimeError("no network")
        with mock.patch.dict(sys.modules, {"db": db}):
            self.assertEqual(cr._live_task_slugs(), set())

    def test_unreachable_database_cannot_produce_already_present(self):
        # losing the queue costs precision, never safety
        v = cr.classify_item({"kind": "dirty_worktree", "branch": "codex/x",
                              "changes": ["a.py"]}, "/repo", live_slugs=set())
        self.assertNotEqual(v["classification"], cr.ALREADY_PRESENT)

    def test_ledger_write_failure_is_soft(self):
        db = mock.MagicMock()
        db.insert.side_effect = RuntimeError("db down")
        with mock.patch.dict(sys.modules, {"db": db}):
            self.assertFalse(cr.write_ledger_record({"a": 1}))

    def test_existing_keys_survives_bad_payloads(self):
        db = mock.MagicMock()
        db.select.return_value = [{"payload": "{not json"}, {"payload": None},
                                  {"payload": json.dumps({"fingerprint": FP,
                                                          "item_key": "k1"})}]
        with mock.patch.dict(sys.modules, {"db": db}):
            self.assertEqual(cr._existing_keys(FP), {"k1"})

    def test_missing_scanner_falls_back_to_the_builtin_walker(self):
        with mock.patch.object(cr, "_load_scanner", return_value=None), \
             mock.patch.object(cr, "_walk_codex", return_value={"beethoven": []}) as w:
            cr.enumerate_evidence(app="beethoven")
        w.assert_called_once()

    def test_walker_on_a_missing_root_is_empty(self):
        self.assertEqual(cr._walk_codex("/no/such/codex/root"), {})


class ReadOnlyTest(unittest.TestCase):
    """The evidence is read-only. This is the prohibition in the reconcile contract.

    Asserted structurally rather than by grepping for words: 'commit' appears legitimately
    in `{sha}^{commit}` and in the ledger record's `commit` field, so a substring scan
    produces false positives and would eventually be deleted for crying wolf. Walk the AST
    instead and check the actual git subcommand at every call site.
    """

    READ_ONLY_SUBCOMMANDS = {
        "merge-base", "cat-file", "ls-remote", "diff", "rev-parse", "status",
        "log", "show", "rev-list", "for-each-ref", "name-rev",
    }

    def _git_subcommands(self):
        import ast
        tree = ast.parse(open(cr.__file__).read())
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name != "_git" or len(node.args) < 2:
                continue
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                found.append(arg.value)
            else:
                found.append(f"<dynamic:{ast.dump(arg)[:40]}>")
        return found

    def test_every_git_call_uses_a_read_only_subcommand(self):
        subs = self._git_subcommands()
        self.assertTrue(subs, "expected at least one _git call site")
        for sub in subs:
            self.assertIn(sub, self.READ_ONLY_SUBCOMMANDS,
                          f"git {sub} is not a read-only subcommand")

    def test_no_dynamic_git_subcommands(self):
        # a computed subcommand cannot be audited statically, so it is banned outright
        for sub in self._git_subcommands():
            self.assertFalse(sub.startswith("<dynamic:"), sub)

    def test_no_filesystem_mutation_calls(self):
        src = open(cr.__file__).read()
        for call in ("os.remove", "os.unlink", "shutil.rmtree", "os.rename",
                     "os.replace", "shutil.move", "os.rmdir", "os.truncate"):
            self.assertNotIn(call, src)

    def test_no_write_mode_file_opens(self):
        src = open(cr.__file__).read()
        for mode in ('"w"', "'w'", '"a"', "'a'", '"wb"', "'wb'"):
            self.assertNotIn(f"open({mode}", src)
            self.assertNotIn(f", {mode})", src)


if __name__ == "__main__":
    unittest.main()
