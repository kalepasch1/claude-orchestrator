"""
test_patch_template_conflict_handling.py — integration tests for the patch-template
workflow's rebase-conflict handling, particularly after branch recovery.

Scenarios covered:
  A) missing-branch → repair directive includes agentic-repair category="missing-branch"
  B) missing-branch → recovery → rebase-conflict: conflict detail flows into repair prompt
  C) conflict detail (file names) appears in task note when cap is exhausted
  D) conflict after recovery uses richer directive naming the conflicting files
  E) missing-branch redo cap exhausted → BLOCKED with no rebase attempt
  F) recovery followed by clean rebase → MERGED normally
  G) _rebase_onto_base unit: captures conflict filenames before --abort
  H) _rebase_onto_base unit: returns empty detail on clean rebase
"""
import contextlib
import os
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train
import agentic_repair
import merge_truth
import minimal_commit


# ── shared helpers ─────────────────────────────────────────────────────────────

def _card(cid, slug, kind="integrate", decided_by=None, created_at="2026-01-01T00:00:00"):
    return {"id": cid, "slug": slug, "kind": kind, "status": "approved",
            "decided_by": decided_by, "created_at": created_at, "title": f"merge of {slug}"}


def _task(tid, slug, project_id="p1", state="BLOCKED", retries=0, remediation=0):
    return {"id": tid, "slug": slug, "project_id": project_id, "state": state,
            "transient_retries": retries, "base_branch": None,
            "remediation_count": remediation, "prompt": f"Implement {slug}.",
            "model": None, "force_coder": None, "kind": "build", "attempt": 1,
            "material": False}


PROJECTS = [{"id": "p1", "name": "alpha", "repo_path": "/tmp/fake-repo",
             "default_base": "main", "test_cmd": "true"}]


class _AnySlug(frozenset):
    """Matches every slug — stands in for "the query carried no slug filter"."""

    def __contains__(self, item):
        return True


class ConflictHandlingCase(unittest.TestCase):
    """Shared harness identical to TrainCase in test_merge_train.py."""

    def setUp(self):
        self.updates = []
        self.cards = []
        self.tasks = []

        self.mock_db = MagicMock()
        self.mock_db.select.side_effect = self._select
        self.mock_db.update.side_effect = \
            lambda table, match, patch: self.updates.append((table, match, patch))
        self.mock_db.select_all.side_effect = self._select_all
        self.mock_db.localize_repo_path.side_effect = lambda p: p

        # HARNESS REPAIR: this list had fallen behind _integrate_card's real surface, so
        # every card died on real git/worktree plumbing against the non-existent
        # /tmp/fake-repo (integration_runtime.isolated_repo -> FileNotFoundError), was
        # swallowed by process_project()'s "worktree vanished mid-pass" handler and counted
        # as `skipped`. Every outcome assertion below was therefore checking a pass that
        # never ran a card. Brought back in line with TrainCase in test_merge_train.py,
        # which this class's docstring already claims to mirror: the gates mocked green
        # here are real merge-blocking steps that own their own test files, so mocking them
        # keeps these tests about the TRAIN's conflict/missing-branch control flow.
        patches = [
            patch.object(merge_train, "db", self.mock_db),
            patch.object(merge_train, "_branch_exists", return_value=True),
            patch.object(merge_train, "_materialize_branch", return_value=True),
            patch.object(merge_train, "_refresh_base", return_value=None),
            patch.object(merge_train, "_rebase_onto_base", return_value=(True, "")),
            patch.object(merge_train, "_run_tests", return_value=(True, "green")),
            patch.object(merge_train, "_ff_base", return_value=True),
            patch.object(merge_train, "_push_base", return_value=""),
            patch.object(merge_train, "_git",
                         return_value=subprocess.CompletedProcess([], 0, stdout="", stderr="")),
            patch.object(merge_train, "_already_integrated", return_value=False),
            patch.object(merge_train, "_post_fork_regression", return_value=(True, "")),
            patch.object(merge_train, "_regression_gate", return_value=(True, "")),
            patch.object(merge_train, "_divergent_gate", return_value=(True, "")),
            patch.object(merge_train, "_stub_gate", return_value=(True, "")),
            patch.object(merge_train, "_orphan_import_gate", return_value=(True, "")),
            patch.object(merge_train, "_build_gate", return_value=(True, "")),
            patch.object(merge_train, "_verify_push", return_value=""),
            patch.object(merge_train.delivery_lease, "ensure", return_value="test-lease"),
            patch.object(merge_train.delivery_lease, "release_all", return_value=None),
            # The minimal-extraction step (_integrate_card step 2b) runs on the
            # rebase-conflict path and would re-run the rebase. Declined here so the
            # conflict tests below assert the redo/CONFLICT behaviour they are named for.
            patch.object(minimal_commit, "extract",
                         return_value={"ok": False, "reason": "test: extraction declined"}),
            # _task_patch routes writes through merge_truth.gate_merged_patch, which cannot
            # resolve a repo for these fake projects and correctly returns None, so the
            # MERGED write would never happen. The gate has its own test file.
            patch.object(merge_truth, "gate_merged_patch",
                         side_effect=lambda task, patch, **kw: patch),
            patch.object(merge_train, "_freeze_integration_identity",
                         return_value={"artifact_commit": "rebased-sha"}),
            patch.object(merge_train, "_delete_branch", return_value=None),
            patch.object(merge_train.approval_merge, "_free_branch", return_value=None),
            patch.object(merge_train, "_paused", return_value=False),
            patch.object(merge_train.os.path, "isdir", return_value=True),
            patch.object(merge_train.integration_runtime, "global_lease",
                         side_effect=lambda *_a, **_k: contextlib.nullcontext(True)),
            patch.object(merge_train.integration_runtime, "isolated_repo",
                         side_effect=lambda repo, *_a, **_k: contextlib.nullcontext(repo)),
        ]
        self.mocks = {}
        for p in patches:
            m = p.start()
            self.addCleanup(p.stop)
            name = getattr(p, "attribute", None)
            if name:
                self.mocks[name] = m

    def _select(self, table, params=None):
        # WAS: the tasks branch did `params["slug"].split("eq.", 1)[1]`, which assumed every
        # task lookup is a single-slug `eq.` filter. train_run() resolves tasks through
        # _resolve_tasks_batch(), which issues ONE `slug=in.(a,b,c)` query for the whole pass,
        # so every test that reached train_run() died with IndexError inside the fake DB — the
        # harness, not the product, was wrong. Both PostgREST filter forms are honoured now.
        if table == "approvals":
            return list(self.cards)
        if table == "projects":
            return list(PROJECTS)
        if table == "tasks":
            return [t for t in self.tasks if t["slug"] in self._wanted_slugs(params)]
        if table == "controls":
            return []
        return []

    def _select_all(self, table, params=None, **kwargs):
        """db.select_all() pages a filtered read to exhaustion; here one page is all of it."""
        return self._select(table, params)

    @staticmethod
    def _wanted_slugs(params):
        """Slugs matched by a PostgREST `eq.` / `in.(...)` filter; None means "no filter"."""
        raw = str((params or {}).get("slug") or "")
        if raw.startswith("eq."):
            return {raw[3:]}
        if raw.startswith("in.("):
            return {s.strip() for s in raw[4:].rstrip(")").split(",") if s.strip()}
        return _AnySlug()

    def task_updates(self, tid):
        return [p for (tbl, m, p) in self.updates if tbl == "tasks" and m.get("id") == tid]

    def card_updates(self, cid):
        return [p for (tbl, m, p) in self.updates if tbl == "approvals" and m.get("id") == cid]

    def last_task_patch(self, tid):
        ups = self.task_updates(tid)
        return ups[-1] if ups else {}


# ── A: missing-branch repair directive ────────────────────────────────────────

class TestMissingBranchDirective(ConflictHandlingCase):

    def test_missing_branch_triggers_agentic_repair(self):
        """Missing branch → repair_patch must use category='missing-branch'."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED", retries=0)]
        self.mocks["_materialize_branch"].return_value = False

        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["redo"], 1)
        tp = self.last_task_patch("t1")
        self.assertEqual(tp["state"], "QUEUED")
        self.assertIn("agentic-repair:missing-branch", tp.get("note", ""))

    def test_missing_branch_redo_increments_transient_retries(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED", retries=0)]
        self.mocks["_materialize_branch"].return_value = False

        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "3"}):
            merge_train.train_run()

        tp = self.last_task_patch("t1")
        self.assertEqual(tp["transient_retries"], 1)

    def test_missing_branch_does_not_consume_approval_card(self):
        """Card must stay live (no decided_by) while branch is being rebuilt."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED", retries=0)]
        self.mocks["_materialize_branch"].return_value = False

        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            merge_train.train_run()

        self.assertEqual(self.card_updates("c1"), [],
                         "card must remain untouched so the train can pick it up after recovery")

    def test_missing_branch_redo_cap_exhausted_blocks_task(self):
        """After cap exhausted, task becomes BLOCKED not QUEUED."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED", retries=2)]
        self.mocks["_materialize_branch"].return_value = False

        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(self.last_task_patch("t1")["state"], "BLOCKED")
        # rebase must never be attempted for a missing branch
        self.mocks["_rebase_onto_base"].assert_not_called()


# ── B/D: conflict detail flows into repair prompt ─────────────────────────────

class TestConflictDetailPropagation(ConflictHandlingCase):

    def test_conflict_detail_appears_in_task_note(self):
        """Conflicting file names must appear in the task note when rebase fails."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=0)]
        self.mocks["_rebase_onto_base"].return_value = (False, "src/pricing.py\nsrc/utils.py")

        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            merge_train.train_run()

        tp = self.last_task_patch("t1")
        # The repair patch prompt must mention the conflicting files
        repair_prompt = tp.get("prompt", "")
        self.assertIn("src/pricing.py", repair_prompt)
        self.assertIn("src/utils.py", repair_prompt)

    def test_conflict_with_no_detail_still_requeues(self):
        """Empty conflict detail must not prevent redo — graceful degradation."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=0)]
        self.mocks["_rebase_onto_base"].return_value = (False, "")

        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["redo"], 1)
        self.assertEqual(self.last_task_patch("t1")["state"], "QUEUED")

    def test_conflict_detail_in_exhausted_task_note(self):
        """When cap is exhausted, conflict file names must appear in the task note."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=2)]
        self.mocks["_rebase_onto_base"].return_value = (False, "runner/merge_train.py")

        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["conflict"], 1)
        note = self.last_task_patch("t1").get("note", "")
        self.assertIn("runner/merge_train.py", note)
        self.assertEqual(self.last_task_patch("t1")["state"], "CONFLICT")

    def test_conflict_detail_in_repair_directive_after_recovery(self):
        """Simulate a task that was already retried once (branch recovery), then hits conflict.

        The repair directive must name the specific files so the agentic coder
        knows exactly where to resolve the conflict.
        """
        self.cards = [_card("c1", "feat-x")]
        # transient_retries=1 means one missing-branch redo already happened
        self.tasks = [_task("t1", "feat-x", retries=1, remediation=1)]
        self.mocks["_rebase_onto_base"].return_value = (False, "src/orders.py")

        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "3"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["redo"], 1)
        tp = self.last_task_patch("t1")
        self.assertEqual(tp["transient_retries"], 2)
        # Both the failure context and directive must name the conflicting file
        repair_prompt = tp.get("prompt", "")
        self.assertIn("src/orders.py", repair_prompt)


# ── C: cap-exhausted state ────────────────────────────────────────────────────

class TestConflictCapExhausted(ConflictHandlingCase):

    def test_cap_exhausted_marks_conflict_not_queued(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=2)]
        self.mocks["_rebase_onto_base"].return_value = (False, "")

        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(self.last_task_patch("t1")["state"], "CONFLICT")
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:conflict-exhausted")
        # no branch deletion at cap-exhausted (task needs manual inspection)
        self.mocks["_delete_branch"].assert_not_called()

    def test_cap_1_conflict_exhausted_immediately(self):
        """With cap=1, a single conflict at retries=1 should exhaust immediately."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=1)]
        self.mocks["_rebase_onto_base"].return_value = (False, "")

        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "1"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(self.last_task_patch("t1")["state"], "CONFLICT")


# ── E: RUNNING tasks wait without redo ────────────────────────────────────────

class TestRunningTaskWaits(ConflictHandlingCase):

    def test_running_task_with_missing_branch_waits(self):
        """A RUNNING task with no branch yet must NOT trigger redo — it's still building."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="RUNNING")]
        self.mocks["_materialize_branch"].return_value = False

        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(self.task_updates("t1"), [],
                         "RUNNING task must not be patched at all")
        self.mocks["_rebase_onto_base"].assert_not_called()


# ── F: recovery followed by clean rebase merges normally ──────────────────────

class TestRecoveryThenCleanMerge(ConflictHandlingCase):

    def test_recovered_branch_merges_when_rebase_clean(self):
        """After a missing-branch redo (retries=1), clean rebase → MERGED."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=1, remediation=1)]
        # branch now exists (was recovered), rebase is clean
        self.mocks["_branch_exists"].return_value = True
        self.mocks["_rebase_onto_base"].return_value = (True, "")

        summary = merge_train.train_run()

        self.assertEqual(summary["merged"], 1)
        self.assertEqual(self.last_task_patch("t1")["state"], "MERGED")
        self.mocks["_ff_base"].assert_called_once()


# ── G/H: _rebase_onto_base unit tests with real git ──────────────────────────

class TestRebaseOntoBaseUnit(unittest.TestCase):
    """Unit tests for _rebase_onto_base using a real minimal git repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        repo = self.tmpdir
        # Init repo
        self._git(repo, "init", "-b", "main")
        self._git(repo, "config", "user.email", "test@test.com")
        self._git(repo, "config", "user.name", "Test")
        # Seed a file and commit on main
        fpath = os.path.join(repo, "file.txt")
        with open(fpath, "w") as f:
            f.write("line1\nline2\n")
        self._git(repo, "add", "file.txt")
        self._git(repo, "commit", "-m", "init")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _git(self, repo, *args):
        return subprocess.run(["git"] + list(args), cwd=repo,
                              capture_output=True, text=True, check=False)

    def _base_sha(self):
        return self._git(self.tmpdir, "rev-parse", "HEAD").stdout.strip()

    def _sha(self, ref):
        return self._git(self.tmpdir, "rev-parse", ref).stdout.strip()

    def _branch_with_change(self, branch, content):
        """Create a branch from HEAD with a change to file.txt."""
        base = self._base_sha()
        self._git(self.tmpdir, "checkout", "-b", branch)
        with open(os.path.join(self.tmpdir, "file.txt"), "w") as f:
            f.write(content)
        self._git(self.tmpdir, "add", "file.txt")
        self._git(self.tmpdir, "commit", "-m", f"change on {branch}")
        self._git(self.tmpdir, "checkout", "main")
        return base

    def test_clean_rebase_returns_ok_empty_detail(self):
        """A base that moved under the branch rebases cleanly: (True, '') and a rewrite.

        WAS: byte-identical to test_already_on_base_returns_ok below — it branched from
        HEAD and never advanced main, so `merge-base --is-ancestor base branch` succeeded
        and _rebase_onto_base returned on its early-exit line. No rebase was ever run, so
        "clean rebase" was asserted by a test that could not tell a working rebase from a
        broken one. main now advances on a different file first, which forces the real
        `git rebase` path, and the branch tip must actually be rewritten onto it.
        """
        self._branch_with_change("feature", "feature-side\n")
        before = self._sha("feature")
        # Advance main on an unrelated file so `feature` is no longer a descendant.
        with open(os.path.join(self.tmpdir, "other.txt"), "w") as f:
            f.write("main moved on\n")
        self._git(self.tmpdir, "add", "other.txt")
        self._git(self.tmpdir, "commit", "-m", "main advances elsewhere")

        ok, detail = merge_train._rebase_onto_base(self.tmpdir, "feature", "main")

        self.assertTrue(ok)
        self.assertEqual(detail, "")
        self.assertNotEqual(self._sha("feature"), before, "the branch must be replayed onto main")
        self.assertEqual(
            self._git(self.tmpdir, "merge-base", "--is-ancestor", "main", "feature").returncode, 0,
            "after a clean rebase the branch must contain the current base")

    def test_already_on_base_is_a_no_op(self):
        """Branch already descended from base → (True, '') with the tip left untouched.

        WAS: named test_already_on_base_returns_ok and identical in body to the test above;
        it asserted (True, '') without ever showing the branch is left alone, which is the
        only thing the early-exit branch of _rebase_onto_base actually promises.
        """
        self._branch_with_change("feature", "ahead\n")
        before = self._sha("feature")

        ok, detail = merge_train._rebase_onto_base(self.tmpdir, "feature", "main")

        self.assertTrue(ok)
        self.assertEqual(detail, "")
        self.assertEqual(self._sha("feature"), before,
                         "a branch that already contains base must not be rewritten")

    def test_conflict_returns_false_with_filenames(self):
        """Conflicting rebase returns (False, <conflicting-filename>)."""
        # Advance main with a change to the same line that feature will also change
        with open(os.path.join(self.tmpdir, "file.txt"), "w") as f:
            f.write("main-side-change\n")
        self._git(self.tmpdir, "add", "file.txt")
        self._git(self.tmpdir, "commit", "-m", "main advances")

        # Create feature from the original commit (before main advanced)
        original_sha = self._git(self.tmpdir, "rev-parse", "HEAD~1").stdout.strip()
        self._git(self.tmpdir, "checkout", "-b", "feature", original_sha)
        with open(os.path.join(self.tmpdir, "file.txt"), "w") as f:
            f.write("feature-side-change\n")
        self._git(self.tmpdir, "add", "file.txt")
        self._git(self.tmpdir, "commit", "-m", "feature change")
        self._git(self.tmpdir, "checkout", "main")

        ok, detail = merge_train._rebase_onto_base(self.tmpdir, "feature", "main")

        self.assertFalse(ok)
        # The conflicting file should be named
        self.assertIn("file.txt", detail)
        # Rebase should have been aborted — no leftover conflict markers in the index
        # (git rebase base branch switches HEAD to branch, so HEAD may be on feature)
        conflicts = self._git(self.tmpdir, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        self.assertEqual(conflicts, "", "rebase --abort must leave no unresolved conflicts")


# ── patch_templates: inject_prompt and pre_claim_hook ─────────────────────────

class TestPatchTemplateHooks(unittest.TestCase):
    """patch_templates.inject_prompt / pre_claim_hook must not crash on edge inputs."""

    def setUp(self):
        import patch_templates
        self.pt = patch_templates

    def test_inject_prompt_idempotent(self):
        """inject_prompt must not double-inject if the mark is already present."""
        task = {"slug": "t1", "prompt": "Do something.\n[patch-template:abc123]\n"}
        result = self.pt.inject_prompt(task)
        self.assertEqual(result["prompt"].count("[patch-template:"), 1)

    def test_inject_prompt_adds_template(self):
        task = {"slug": "t1", "prompt": "Implement feature X."}
        result = self.pt.inject_prompt(task)
        self.assertIn("[patch-template:", result["prompt"])
        self.assertIn("Implement feature X.", result["prompt"])

    def test_pre_claim_hook_enriches_the_prompt_when_the_db_is_down(self):
        """A dead DB must cost the template store, not the template.

        WAS: it set `mock_db.update.side_effect` and asserted the result was a dict whose
        slug was "t1". pre_claim_hook has not called db.update since the 2026-07-11 fix
        that removed the prompt-corrupting write-back (see its docstring), so the test
        configured a mock that is never consulted and then asserted a key it had itself
        put into the input dict — green whatever the hook did. The real DB surface the
        hook touches is db.insert (via _store) and db.select (via _ensure_branch/
        _get_project); failing THOSE is the fail-soft path worth pinning.
        """
        import patch_templates
        task = {"id": "x", "slug": "t1", "prompt": "Do it."}
        with patch.object(patch_templates, "db") as mock_db:
            mock_db.insert.side_effect = Exception("db offline")
            mock_db.select.side_effect = Exception("db offline")
            result = patch_templates.pre_claim_hook(task)
        self.assertIn(patch_templates.MARK, result["prompt"],
                      "the scaffold must still be injected when the store is unreachable")
        self.assertIn("Do it.", result["prompt"], "the caller's own prompt must survive")
        self.assertEqual(task["prompt"], "Do it.",
                         "the input task must not be mutated in place")

    def test_pre_claim_hook_none_task(self):
        import patch_templates
        # Must not crash on None
        result = patch_templates.pre_claim_hook(None)
        self.assertIsNone(result)  # returns the original None

    def test_inject_prompt_empty_prompt(self):
        task = {"slug": "t1", "prompt": ""}
        result = self.pt.inject_prompt(task)
        self.assertIn("[patch-template:", result["prompt"])


# ── agentic_repair: repair_prompt embeds conflict detail ──────────────────────

class TestRepairPromptConflictDetail(unittest.TestCase):

    def test_conflict_detail_in_failure_text(self):
        """repair_prompt must embed the conflict file names in the failure context."""
        task = {"slug": "feat-x", "id": "t1", "prompt": "Implement feat-x.",
                "model": None, "kind": "build"}
        failure = "train: rebase conflict on agent/feat-x against main. Conflicting files: src/foo.py\nsrc/bar.py."
        prompt = agentic_repair.repair_prompt(task, failure,
                                              "Rebuild on fresh main.", category="conflict")
        self.assertIn("src/foo.py", prompt)
        self.assertIn("src/bar.py", prompt)
        self.assertIn("Repair category: conflict", prompt)

    def test_repair_prompt_contains_agentic_repair_marker(self):
        task = {"slug": "feat-x", "id": "t1", "prompt": "Do it.",
                "model": None, "kind": "build"}
        prompt = agentic_repair.repair_prompt(task, "some failure", "Fix it.", category="conflict")
        self.assertIn(agentic_repair.MARKER, prompt)

    def test_repair_patch_returns_queued_state(self):
        task = {"slug": "feat-x", "id": "t1", "prompt": "Do it.",
                "model": None, "force_coder": None, "kind": "build",
                "remediation_count": 0, "attempt": 1}
        patch_dict = agentic_repair.repair_patch(task, "conflict!", category="conflict")
        self.assertEqual(patch_dict["state"], "QUEUED")
        self.assertIn("conflict", patch_dict.get("note", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
