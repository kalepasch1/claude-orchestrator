"""
Test suite for relfix-pareto-2080: release conflict self-healing and patch transplant.

Tests cover:
- Release conflict detection and classification (clean vs conflicting files)
- Self-healing decomposition of branches into non-conflicting sub-branches
- Patch transplant from prior proven diffs (adapt vs rebuild)
- Security validation gates before merge
- Legal gate checking (licensing, transmission, custody rules)
- Ephemeral worktree isolation (never touch main checkout)
- Concurrent merge operations with race condition safety
- Auto-merge to orchestrator/dev after QA passes
- Fallback to local repair tasks when healing fails
- Release train batch coordination and cadence gates

NOTE ON THIS FILE'S HISTORY
---------------------------
This suite was originally written against an API that never existed:
`self_healing_merge.db`, `.attempt_merge`, `.check_security_gate`,
`.check_legal_gate`, `.automerge_after_qa`, `.find_transplant_source`,
`release_train.ensure_staging_branch` / `.merge_to_staging` /
`.promote_staging_to_prod` / `.check_red_gate`. None of those are real. The
behaviours they were reaching for DO exist, spread across
`self_healing_merge` (heal/_classify_files/_create_sub_branch/
_create_repair_tasks/stats), `patch_transplant` (the transplant + security
gate), `legal_filter` (the owner-approval gate) and `release_train`
(_ensure_staging/_merge_into_staging/_release_decision/_recent_failed_gate).
Each test below now targets the real function; where the mapping is not
one-to-one the substitution is explained in the test's own comment.
"""
import os
import subprocess
import sys
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import legal_filter
import patch_transplant
import release_train
import self_healing_merge
import transplant_discipline


def _cp(args, returncode=0, stdout="", stderr=""):
    """A CompletedProcess shaped like the one self_healing_merge._git returns.

    _git runs with text=True, so stdout/stderr are `str`. Several tests in the
    original file handed back `bytes`, which made `.splitlines()` yield bytes
    filenames that could never match the str paths the module compares them to.
    """
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class FakeGit:
    """Stand-in for `self_healing_merge._git` that answers by git subcommand.

    The module's call order is an implementation detail (it changed when
    classification moved into an ephemeral worktree), so a positional
    `side_effect` list silently mis-assigns answers to commands — that is how
    the original tests ended up feeding a "checkout base" result into the merge
    attempt and concluding a conflicted branch was clean. Dispatching on argv
    keeps each answer attached to the command it actually answers, and records
    every call so tests can assert *where* work happened.
    """

    def __init__(self, merge_rc=0, merge_stderr="", head="master", dirty="",
                 show_content="content\n"):
        self.calls = []
        self.merge_rc = merge_rc
        self.merge_stderr = merge_stderr
        self.head = head
        self.dirty = dirty
        self.show_content = show_content

    def __call__(self, args, repo, timeout=None):
        self.calls.append((tuple(args), repo))
        sub = args[1] if len(args) > 1 else ""
        if sub == "-c":                       # git -c user.name=... commit -m ...
            sub = "commit"
        if sub == "merge-base":
            return _cp(args, 0, "base123\n")
        if sub == "rev-parse":
            return _cp(args, 0, "presha123\n")
        if sub == "show":
            return _cp(args, 0, self.show_content)
        if sub == "branch" and "--show-current" in args:
            return _cp(args, 0, self.head + "\n")
        if sub == "status":
            return _cp(args, 0, self.dirty)
        if sub == "merge" and "--abort" not in args:
            return _cp(args, self.merge_rc, "", self.merge_stderr)
        return _cp(args, 0, "")

    def argvs(self):
        return [c[0] for c in self.calls]

    def cwds_for(self, *subcommands):
        """Working directories used for the given git subcommands."""
        return [repo for argv, repo in self.calls
                if len(argv) > 1 and argv[1] in subcommands]


class TestReleaseConflictDetection(unittest.TestCase):
    """Classify files into clean vs conflicting.

    `_classify_files` issues, in order:
      1 merge-base, 2 diff --name-only, 3 worktree add --detach,
      4 merge --no-commit --no-ff (inside the worktree),
      5 merge --abort, 6 worktree remove, 7 worktree prune.
    The original mocks described a "checkout base" step at position 4 and a
    second "diff --name-only" for the conflict list — neither exists; conflicts
    are parsed out of the merge output.
    """

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("self_healing_merge._git")
    def test_classify_files_all_clean(self, mock_git):
        """All changed files are clean (non-conflicting) when merge succeeds."""
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),                              # merge-base
            _cp([], 0, "file1.py\nfile2.py\nfile3.py\n"),         # diff --name-only
            _cp([], 0),                                           # worktree add --detach
            _cp([], 0),                                           # merge --no-commit (clean)
            _cp([], 0), _cp([], 0), _cp([], 0),                   # abort/remove/prune
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert result["clean"] == ["file1.py", "file2.py", "file3.py"]
        assert result["conflicting"] == []
        assert len(result["all_changed"]) == 3

    @patch("self_healing_merge._git")
    def test_classify_files_mixed_clean_and_conflicting(self, mock_git):
        """Some files are clean, some are conflicting.

        Was: fed a "checkout base" mock into the merge slot and then expected a
        separate `diff --name-only` to report the conflict set. The module has
        no such step — it parses git's own "CONFLICT (content): Merge conflict
        in <path>" lines out of the failed merge, so the merge result has to
        carry that text for the classification to mean anything.
        """
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, "clean1.py\nclean2.py\nconflict.py\n"),
            _cp([], 0),
            _cp([], 1, "", "CONFLICT (content): Merge conflict in conflict.py\n"
                           "Automatic merge failed; fix conflicts.\n"),
            _cp([], 0), _cp([], 0), _cp([], 0),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert result["clean"] == ["clean1.py", "clean2.py"]
        assert result["conflicting"] == ["conflict.py"]

    @patch("self_healing_merge._git")
    def test_classify_files_git_failure_returns_empty(self, mock_git):
        """Git command failures degrade gracefully."""
        mock_git.side_effect = [
            _cp([], 128, "", "not a git repo\n"),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert result == {"clean": [], "conflicting": [], "all_changed": []}

    @patch("self_healing_merge._git")
    def test_classify_files_no_changes_returns_empty(self, mock_git):
        """No changed files between base and branch."""
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, ""),          # diff --name-only: nothing changed
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert result == {"clean": [], "conflicting": [], "all_changed": []}
        # No worktree is created when there is nothing to classify.
        assert mock_git.call_count == 2

    @patch("self_healing_merge._git")
    def test_classify_files_all_conflicting(self, mock_git):
        """All changed files are conflicting.

        Was: asserted 0 clean / 2 conflicting while handing the merge step a
        returncode-0 mock, so the module (correctly) classified everything as
        clean and the test failed. The merge must actually fail, and must name
        both files, for "all conflicting" to be the true answer.
        """
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, "conf1.py\nconf2.py\n"),
            _cp([], 0),
            _cp([], 1, "", "CONFLICT (content): Merge conflict in conf1.py\n"
                           "CONFLICT (content): Merge conflict in conf2.py\n"),
            _cp([], 0), _cp([], 0), _cp([], 0),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert result["clean"] == []
        assert sorted(result["conflicting"]) == ["conf1.py", "conf2.py"]

    @patch("self_healing_merge._git")
    def test_classify_files_worktree_unavailable_is_fail_safe(self, mock_git):
        """A worktree that cannot be created makes every file conflicting.

        The module documents this explicitly: rather than fall back to the old
        stash-the-main-checkout behaviour, it skips healing by declaring the
        whole change set unknown-and-therefore-conflicting, leaving the branch
        to the normal CONFLICT path.
        """
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, "a.py\nb.py\n"),
            _cp([], 128, "", "fatal: could not create worktree\n"),
        ]

        result = self_healing_merge._classify_files(self.repo, "feature", "master")

        assert result["clean"] == []
        assert result["conflicting"] == ["a.py", "b.py"]


class TestSelfHealingDecomposition(unittest.TestCase):
    """Decompose conflicting branches into clean + repair sub-branches."""

    def setUp(self):
        # The original class had no setUp at all but referenced `self.repo`.
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        # _create_sub_branch materialises the clean files in an ephemeral
        # worktree next to the repo (repo + "-wt"); clean that sibling up too.
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    def _classification(self, clean, conflicting):
        return {"clean": list(clean), "conflicting": list(conflicting),
                "all_changed": list(clean) + list(conflicting)}

    @patch("auto_conflict_resolver.verify_merge", return_value="")
    @patch("self_healing_merge._classify_files")
    def test_heal_creates_clean_subbranch_when_partial_clean_exists(
            self, mock_classify, _verify):
        """When some files are clean, create sub-branch and merge it.

        Was: asserted `result["clean_merged"]` and patched `self_healing_merge.db`.
        The module imports db as `_db` and heal() reports the count of files it
        landed under "merged"; there is no "clean_merged" key.
        """
        mock_classify.return_value = self._classification(
            ["file1.py", "file2.py"], ["conflict.py"])
        fake_git = FakeGit()

        with patch.object(self_healing_merge, "_git", fake_git), \
                patch.object(self_healing_merge, "_db") as mock_db:
            result = self_healing_merge.heal(
                repo=self.repo, branch="conflicting-feature", base="master",
                project_id="pareto-2080")

        assert result["healed"] is True
        assert result["merged"] == 2
        assert result["clean_files"] == ["file1.py", "file2.py"]
        # The sub-branch is built from the clean files only...
        shown = [argv for argv in fake_git.argvs() if argv[1] == "show"]
        assert shown == [("git", "show", "conflicting-feature:file1.py"),
                         ("git", "show", "conflicting-feature:file2.py")]
        # ...and the conflicting file becomes a focused repair task.
        assert len(result["repair_tasks"]) == 1
        assert result["repair_tasks"][0]["file_scope"] == "conflict.py"
        assert mock_db.insert.call_args[0][0] == "tasks"

    def test_heal_creates_repair_task_for_conflicting_cluster(self):
        """Conflicting files create a focused repair task.

        Was: patched a `_create_repair_task` that does not exist and asserted
        it was called from a heal() whose classification had zero clean files —
        a run that legitimately stops at "no clean files to extract" before any
        task is created. Substituted: exercise the real
        `_create_repair_tasks`, which is where the cluster-to-task mapping
        lives, and assert the task it builds actually scopes the cluster.
        """
        with patch.object(self_healing_merge, "_db") as mock_db:
            tasks = self_healing_merge._create_repair_tasks(
                ["security.py", "auth.py", "tokens.py"], "sec-upgrade", "pareto-2080")

        assert len(tasks) == 1                       # one directory -> one cluster
        task = tasks[0]
        assert task["slug"].startswith("repair-sec-upgrade")
        assert task["state"] == "QUEUED"
        assert task["project_id"] == "pareto-2080"
        assert task["file_scope"] == "security.py, auth.py, tokens.py"
        assert "sec-upgrade" in task["prompt"]
        mock_db.insert.assert_called_once_with("tasks", task)

    @patch("self_healing_merge._classify_files")
    def test_heal_skip_when_disabled_via_env(self, mock_classify):
        """Healing is disabled by ORCH_SELF_HEALING_ENABLED=false.

        Was: patched os.environ and expected reason == "disabled". The kill
        switch is read into `ENABLED` at import time, so mutating the
        environment mid-process changes nothing; the flag itself is the thing
        to flip, and the reason the module reports is "self-healing disabled".
        """
        with patch.object(self_healing_merge, "ENABLED", False):
            result = self_healing_merge.heal(
                repo=self.repo, branch="feature", base="master")

        assert result["healed"] is False
        assert result["reason"] == "self-healing disabled"
        assert not mock_classify.called          # disabled means no git work at all

    @patch("self_healing_merge._classify_files")
    def test_heal_skip_when_too_few_files(self, mock_classify):
        """Branches with fewer than MIN_FILES changed are not healed."""
        mock_classify.return_value = self._classification([], ["single.py"])
        fake_git = FakeGit()

        with patch.object(self_healing_merge, "_git", fake_git), \
                patch.object(self_healing_merge, "MIN_FILES", 2):
            result = self_healing_merge.heal(
                repo=self.repo, branch="tiny-fix", base="master")

        assert result["healed"] is False
        assert "too few files" in result["reason"]
        assert fake_git.calls == []              # bails out before touching git

    @patch("auto_conflict_resolver.verify_merge", return_value="")
    @patch("self_healing_merge._classify_files")
    def test_heal_uses_ephemeral_worktree_never_touches_main_checkout(
            self, mock_classify, _verify):
        """Healing uses worktrees, never stashes on main checkout.

        Was: a loop that could only assert anything if a stash command showed
        up, i.e. it passed vacuously. This is the module's headline root-cause
        fix ("agent git work never happens in the main checkout"), so assert it
        directly: no stash/reset/checkout is ever aimed at the repo, the
        sub-branch is built under repo + "-wt", and the only command run in the
        main checkout that changes anything is the final fast merge.
        """
        mock_classify.return_value = self._classification(["file.py"], ["conflict.py"])
        fake_git = FakeGit()

        with patch.object(self_healing_merge, "_git", fake_git), \
                patch.object(self_healing_merge, "_db"):
            self_healing_merge.heal(repo=self.repo, branch="feature", base="master")

        for argv, cwd in fake_git.calls:
            if cwd == self.repo:
                assert argv[1] != "stash", f"stashed the main checkout: {argv}"
                assert argv[1] != "checkout", f"checked out in the main checkout: {argv}"
                assert not (argv[1] == "reset" and "--hard" in argv), \
                    f"reset --hard in the main checkout: {argv}"
        # checkout -b for the sub-branch happened, and happened in the worktree
        checkout_cwds = fake_git.cwds_for("checkout")
        assert checkout_cwds, "expected the sub-branch to be created somewhere"
        for cwd in checkout_cwds:
            assert cwd.startswith(self.worktree_root)

    @patch("auto_conflict_resolver.verify_merge", return_value="")
    @patch("self_healing_merge._classify_files")
    def test_heal_returns_partial_when_clean_merged_but_conflicts_remain(
            self, mock_classify, _verify):
        """heal reports a partial heal when some files merged but conflicts persist.

        Was: asserted `result["partial"]`, a key heal() never sets. Partiality
        is reported in the reason string and counted in the module's stats.
        """
        mock_classify.return_value = self._classification(["clean.py"], ["conflict.py"])
        before = self_healing_merge.stats()["partial"]

        with patch.object(self_healing_merge, "_git", FakeGit()), \
                patch.object(self_healing_merge, "_db"):
            result = self_healing_merge.heal(
                repo=self.repo, branch="mixed-branch", base="master")

        assert result["healed"] is True
        assert result["merged"] == 1
        assert result["conflicting_files"] == ["conflict.py"]
        assert result["reason"] == ("partial heal: merged 1/2 clean files, "
                                    "1 conflicting remain")
        assert self_healing_merge.stats()["partial"] == before + 1

    @patch("auto_conflict_resolver.verify_merge",
           return_value="regression: branch drops export `useCart`")
    @patch("self_healing_merge._classify_files")
    def test_heal_rolls_back_when_anti_loss_gate_finds_a_regression(
            self, mock_classify, _verify):
        """A clean sub-branch merge that loses work is rolled back, not shipped.

        This is the ANTI-LOSS GATE the module documents: "merges cleanly" is not
        "loses nothing", so on findings the merge is reset and the sub-branch is
        preserved as possibly the only copy of the work.
        """
        mock_classify.return_value = self._classification(["clean.py"], ["conflict.py"])
        fake_git = FakeGit()

        with patch.object(self_healing_merge, "_git", fake_git), \
                patch.object(self_healing_merge, "_db"):
            result = self_healing_merge.heal(
                repo=self.repo, branch="lossy", base="master")

        assert result["healed"] is False
        assert "REGRESSION BLOCKED" in result["reason"]
        assert any(argv[:3] == ("git", "reset", "--hard") for argv in fake_git.argvs())
        # The sub-branch must survive: only a *successful* merge deletes it.
        assert not any(argv[:2] == ("git", "branch") and "-d" in argv
                       for argv in fake_git.argvs())


class TestPatchTransplant(unittest.TestCase):
    """Adapt proven patches from prior diffs.

    Transplant lives in `patch_transplant`, not `self_healing_merge` — the
    latter has no db handle named `db`, no `compute_similarity`, no
    `find_transplant_source`, `adapt_patch` or `apply_patch`. These tests were
    re-pointed at the module that actually implements the behaviour.
    """

    @patch("patch_transplant.db.select")
    def test_find_similar_patch_by_similarity_threshold(self, mock_select):
        """A prior patch above the caller's floor is offered for transplant."""
        mock_select.return_value = [{
            "slug": "deployfix-beethoven-07190257",
            "project": "beethoven",
            "task_class": "deployfix",
            "similarity": 0.261,
            "patch_diff": "--- a/fleet_config.py\n+++ b/fleet_config.py\n",
        }]

        found = patch_transplant.find_transplant_source(
            {"id": "relfix-pareto-2080-07171927"}, min_similarity=0.25)

        assert found is not None
        assert found["slug"] == "deployfix-beethoven-07190257"
        assert found["similarity"] == 0.261

    @patch("patch_transplant.db.select")
    def test_find_similar_patch_respects_the_single_fleet_floor(self, mock_select):
        """With no explicit floor the fleet-wide 0.55 applies, and 0.261 is out.

        The module carries a long note about this: two floors (0.18 in hint(),
        0.25 here) used to disagree, which is exactly where "adapt the proven
        patch beethoven/deployfix-... similarity=0.26" prompts came from.
        """
        mock_select.return_value = [{
            "slug": "deployfix-beethoven-07190257", "similarity": 0.261,
        }]

        assert transplant_discipline.MIN_TRANSPLANT_SIMILARITY == 0.55
        assert patch_transplant.find_transplant_source(
            {"id": "relfix-pareto-2080-07171927"}) is None

    def test_adapt_patch_to_target_branch(self):
        """Adapt prior patch diff to target branch context.

        Was: adapted a diff whose added line was `ORCH_SECURITY_GATE = True`
        and expected that line back. `adapt_patch` is fail-closed on
        security-sensitive additions by design (a reviewed security change must
        not be relocated into a file it was never reviewed against), so the
        real answer there is None. Both halves are asserted below: an ordinary
        change is retargeted, a security-sensitive one is refused.
        """
        prior_diff = ("--- a/fleet_config.py\n"
                      "+++ b/fleet_config.py\n"
                      "@@ -10,3 +10,5 @@\n"
                      " PROFILES = {}\n"
                      "+ORCH_RELEASE_MIN_BATCH = 10\n")

        result = patch_transplant.adapt_patch(
            prior_diff=prior_diff,
            target_task={"project": "pareto-2080"},
            target_files=["release_train.py"])

        assert "ORCH_RELEASE_MIN_BATCH = 10" in result
        assert "--- a/release_train.py" in result
        assert "+++ b/release_train.py" in result
        assert "fleet_config.py" not in result

        sensitive = prior_diff.replace("ORCH_RELEASE_MIN_BATCH = 10",
                                       "ORCH_SECURITY_GATE = True")
        assert patch_transplant.adapt_patch(
            prior_diff=sensitive,
            target_task={"project": "pareto-2080"},
            target_files=["release_train.py"]) is None

    def test_transplant_patch_applies_cleanly(self):
        """Transplanted patch applies without rejects."""
        prior_patch = (b"--- a/test.py\n"
                       b"+++ b/test.py\n"
                       b"@@ -1,3 +1,4 @@\n"
                       b" def foo():\n"
                       b"+    # release note\n"
                       b"     pass\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "test.py"), "w") as f:
                f.write("def foo():\n    pass\n")

            with patch("subprocess.run") as mock_run:
                mock_run.return_value = Mock(returncode=0, stdout=b"", stderr=b"")
                result = patch_transplant.apply_patch(prior_patch, tmpdir)

        assert result == {"applied": True, "rejects": 0}
        # The dry run must come first, and the real apply only after it passes.
        assert [c.args[0] for c in mock_run.call_args_list] == [
            ["patch", "--dry-run", "-p1"], ["patch", "-p1"]]


class TestSecurityValidationGate(unittest.TestCase):
    """Security checks before merge.

    There is no `self_healing_merge.check_security_gate`. The gate that really
    stands between a transplanted change and a merge is
    `patch_transplant.security_findings` / `SECURITY_SENSITIVE`, consulted by
    `adapt_patch`, which refuses rather than degrades. These tests target it.
    """

    def test_security_gate_blocks_transmission_rule_violation(self):
        """Credential transmission added by a patch blocks the transplant."""
        diff = ("--- a/transport.py\n"
                "+++ b/transport.py\n"
                "@@ -1,2 +1,4 @@\n"
                " import requests\n"
                '+headers = {"Authorization": ACCESS_TOKEN}\n'
                '+requests.post("http://internal/relay", headers=headers)\n')

        findings = patch_transplant.security_findings(diff)

        assert findings, "expected the transmission line to be flagged"
        assert any(f.lower() in ("authorization", "access_token") for f in findings)
        assert patch_transplant.adapt_patch(diff, {"project": "pareto-2080"}) is None

    def test_security_gate_blocks_credentials_in_config(self):
        """Config keys carrying secrets are rejected."""
        diff = ("--- a/fleet_config.py\n"
                "+++ b/fleet_config.py\n"
                "@@ -1,2 +1,4 @@\n"
                " PROFILES = {}\n"
                '+AWS_API_KEY = "AKIAIOSFODNN7EXAMPLE"\n'
                '+GITHUB_ACCESS_TOKEN = "ghp_xxx"\n')

        findings = patch_transplant.security_findings(diff)

        assert len(findings) >= 2
        assert patch_transplant.adapt_patch(diff, {"project": "pareto-2080"}) is None

    def test_security_gate_passes_when_no_violations(self):
        """A clean branch passes the gate and is transplanted unchanged."""
        diff = ("--- a/release_train.py\n"
                "+++ b/release_train.py\n"
                "@@ -1,2 +1,3 @@\n"
                " import os\n"
                "+RELEASE_INTERVAL_HOURS = 6\n")

        assert patch_transplant.security_findings(diff) == []
        assert patch_transplant.adapt_patch(diff, {"project": "pareto-2080"}) == diff

    def test_security_gate_judges_added_lines_only(self):
        """Removing a hardcoded secret is not a security violation.

        The module is explicit that judging removed lines would block exactly
        the patches worth transplanting.
        """
        diff = ("--- a/config.py\n"
                "+++ b/config.py\n"
                "@@ -1,2 +1,2 @@\n"
                '-API_KEY = "hardcoded"\n'
                "+key = load_from_vault()\n")

        assert patch_transplant.security_findings(diff) == []
        assert patch_transplant.adapt_patch(diff, {"project": "pareto-2080"}) == diff
        # Sanity check on the other direction: the same token on an ADDED line
        # is what the gate is for.
        added = diff.replace('-API_KEY = "hardcoded"', '+API_KEY = "hardcoded"')
        assert patch_transplant.security_findings(added) == ["API_KEY"]


class TestLegalGateChecking(unittest.TestCase):
    """Legal gate for licensing, registration, transmission.

    `self_healing_merge.check_legal_gate` never existed. The repo's one narrow
    owner/counsel predicate is `legal_filter.requires_owner_approval`, and it
    judges the *description of the work*, not a list of changed filenames —
    which is what "licensing / custody changes need the owner" actually means
    here. Re-pointed accordingly.
    """

    def test_legal_gate_requires_owner_approval_for_licensing_change(self):
        """Work that would force licensing/registration needs the owner."""
        text = ("Add a money transmission flow to pareto-2080; this requires "
                "the company to obtain a money transmitter license and register "
                "as an MSB.")

        assert legal_filter.requires_owner_approval(text=text) is True
        assert "money transmi" in legal_filter.trigger_excerpt(text=text).lower()

    def test_legal_gate_requires_owner_for_custody_transfer(self):
        """Taking custody of customer funds needs the owner."""
        text = ("Change the payout service so pareto-2080 will hold customer "
                "funds in a custodial account before disbursement.")

        assert legal_filter.requires_owner_approval(text=text) is True

    def test_legal_gate_passes_for_normal_code_change(self):
        """Normal code changes pass legal gate."""
        text = "Refactor runner.py and db.py to share one retry helper."

        assert legal_filter.requires_owner_approval(text=text) is False

    def test_legal_gate_does_not_fire_on_safe_positioning(self):
        """Work that *preserves* the legal posture is not a posture change.

        The module's stated policy: do not stop implementation for generic
        regulatory smell — safe-positioning language means the task is keeping
        the strategy, not changing it.
        """
        text = ("Add a disclaimer so the custody comparison page stays "
                "informational and non-custodial: we hold no customer funds.")

        assert legal_filter.requires_owner_approval(text=text) is False


class TestAutoMergeOrchestration(unittest.TestCase):
    """Auto-merge to orchestrator/dev after QA passes.

    `self_healing_merge.automerge_after_qa` does not exist. The real merge of a
    judged branch into the staging branch is
    `release_train._merge_into_staging`, which returns a bool and does the work
    in an ephemeral worktree. Re-pointed; the QA verdict itself is the caller's
    precondition, so the tests below assert the merge behaviour that verdict
    gates.
    """

    def _run_merge(self, merge_rc=0, verify=""):
        recorded = []

        def fake_run(args, **kwargs):
            recorded.append(list(args))
            if "rev-parse" in args:
                return _cp(args, 0, "presha123\n")
            if "merge" in args and "--abort" not in args:
                return _cp(args, merge_rc, "",
                           "" if merge_rc == 0 else
                           "CONFLICT (content): Merge conflict in file.py\n")
            return _cp(args, 0)

        with patch.object(release_train, "_git", return_value=_cp([], 0)) as mock_git, \
                patch("subprocess.run", side_effect=fake_run), \
                patch("auto_conflict_resolver.verify_merge", return_value=verify):
            merged = release_train._merge_into_staging("/repo", "relfix-pareto-2080")
        return merged, recorded, mock_git

    def test_automerge_after_qa_passes(self):
        """A judged branch merges into staging once the gates are green."""
        merged, recorded, mock_git = self._run_merge()

        assert merged is True
        assert ["git", "merge", "--no-ff", "-m", "train: relfix-pareto-2080",
                "relfix-pareto-2080"] in recorded
        # Staging work happens in a throwaway worktree, never the main checkout.
        assert mock_git.call_args_list[0].args[1:4] == ("worktree", "add", "-f")

    def test_automerge_blocked_when_qa_fails(self):
        """A branch whose merge loses work is rolled back, not staged.

        Was: expected an `automerge_after_qa` that read a "qa_status" column and
        returned a reason string. The real staging merge has its own
        fail-closed verdict — the anti-loss gate — and refuses on findings.
        """
        merged, recorded, _ = self._run_merge(verify="stub: file.py replaced by TODO")

        assert merged is False
        assert ["git", "reset", "--hard", "presha123"] in recorded

    def test_automerge_handles_race_with_concurrent_branches(self):
        """A branch that conflicts with what another merge already staged aborts."""
        merged, recorded, _ = self._run_merge(merge_rc=1)

        assert merged is False
        assert ["git", "merge", "--abort"] in recorded
        # Nothing was reset: the merge never committed, so staging is untouched.
        assert not any(r[:2] == ["git", "reset"] for r in recorded)


class TestReleaseTrainCoordination(unittest.TestCase):
    """Batch merging and release cadence gates."""

    def test_release_decision_hold_when_below_batch_minimum(self):
        """Release decision holds when ahead count < minimum."""
        assert release_train._release_decision(ahead=5, due=False, minimum=10) == "hold"

    def test_release_decision_release_when_batch_full(self):
        """Release decision releases when ahead >= minimum."""
        assert release_train._release_decision(ahead=15, due=False, minimum=10) == "release"

    def test_release_decision_flush_when_cadence_due(self):
        """Release decision flushes partial batch when cadence is due."""
        assert release_train._release_decision(ahead=7, due=True, minimum=10) == "release"

    def test_release_decision_up_to_date_when_empty(self):
        """Release decision up-to-date when no branches ahead."""
        assert release_train._release_decision(ahead=0, due=False) == "up-to-date"

    def test_staging_branch_rebased_before_merge(self):
        """Staging is kept current with prod before each merge.

        Was: called `release_train.ensure_staging_branch` (does not exist) and
        asserted a literal `git rebase`. The real `_ensure_staging` never
        rebases — it fast-forwards staging onto prod with a local
        `fetch . <prod>:<staging>` precisely because rebasing a shared
        integration branch would rewrite commits other hosts already pushed.
        Assert the behaviour the docstring promises: staging ends up containing
        prod, without a checkout of the main tree.
        """
        answers = {
            ("rev-parse", "--verify", "refs/remotes/origin/orchestrator/dev"): 1,
            ("rev-parse", "--verify", "orchestrator/dev"): 0,
            ("merge-base", "--is-ancestor", "orchestrator/dev", "master"): 0,
        }
        calls = []

        def fake_git(repo, *args, timeout=None):
            calls.append(args)
            return _cp(list(args), answers.get(args, 0), "")

        with patch.object(release_train, "_git", side_effect=fake_git):
            release_train._ensure_staging("/repo", "master")

        assert ("fetch", ".", "master:orchestrator/dev") in calls
        assert not any(a[0] == "checkout" for a in calls)
        assert not any(a[0] == "rebase" for a in calls)

    def test_staging_branch_created_from_prod_when_missing(self):
        """A project with no staging branch yet gets one, forked off prod."""
        answers = {
            ("rev-parse", "--verify", "refs/remotes/origin/orchestrator/dev"): 1,
            ("rev-parse", "--verify", "orchestrator/dev"): 1,
        }
        calls = []

        def fake_git(repo, *args, timeout=None):
            calls.append(args)
            return _cp(list(args), answers.get(args, 0), "")

        with patch.object(release_train, "_git", side_effect=fake_git):
            release_train._ensure_staging("/repo", "master")

        assert ("branch", "orchestrator/dev", "master") in calls

    def test_merge_to_staging_accumulates_work(self):
        """Agent branches merge into staging without going to prod.

        Was: `release_train.merge_to_staging(...)["merged"]`. The real function
        is `_merge_into_staging(repo, branch) -> bool`, and the point of this
        test is that nothing in it pushes or touches prod.
        """
        recorded = []

        def fake_run(args, **kwargs):
            recorded.append(list(args))
            if "rev-parse" in args:
                return _cp(args, 0, "presha123\n")
            return _cp(args, 0)

        git_calls = []

        def fake_git(repo, *args, timeout=None):
            git_calls.append(args)
            return _cp(list(args), 0)

        with patch.object(release_train, "_git", side_effect=fake_git), \
                patch("subprocess.run", side_effect=fake_run), \
                patch("auto_conflict_resolver.verify_merge", return_value=""):
            merged = release_train._merge_into_staging("/repo", "agent/feature-123")

        assert merged is True
        assert not any(a[0] == "push" for a in git_calls)
        assert not any(r[:2] == ["git", "push"] for r in recorded)

    def test_prod_promotion_records_last_good_commit(self):
        """The rollback point is the REMOTE prod tip, not the local branch.

        Was: `release_train.promote_staging_to_prod(...)["last_good_commit"]` —
        no such function or key. `last_good` (written to projects.last_good_sha
        and to the release row's from_sha) is `release_base_sha`, which comes
        from `_release_base_ref`; the module documents why it must be
        origin/<prod>: a stale or dirty local prod produces duplicate release
        rows for the same staging SHA, i.e. a wrong rollback point.
        """
        calls = []

        def fake_git(repo, *args, timeout=None):
            calls.append(args)
            if args[0] == "rev-parse" and args[-1] == "origin/master":
                return _cp(list(args), 0, "prod-sha-123abc\n")
            return _cp(list(args), 0, "")

        with patch.object(release_train, "_git", side_effect=fake_git):
            base = release_train._release_base_ref("/repo", "master")

        assert base == "origin/master"
        assert ("fetch", "origin", "master") in calls

        # And it degrades to the local branch when there is no remote tracking ref.
        def no_remote(repo, *args, timeout=None):
            if args[0] == "rev-parse" and args[-1] == "origin/master":
                return _cp(list(args), 128, "")
            return _cp(list(args), 0, "")

        with patch.object(release_train, "_git", side_effect=no_remote):
            assert release_train._release_base_ref("/repo", "master") == "master"


class TestConcurrentMergeRaceSafety(unittest.TestCase):
    """Concurrent merge operations don't create phantom conflicts."""

    def test_concurrent_merges_use_upsert_for_idempotency(self):
        """Repeated failures of the same gate on the same SHA record one row.

        Was: `self_healing_merge.record_merge(...)` plus a conditional assert
        that could not fail. The real idempotency guard on this path is
        `_recent_failed_gate`, which `_insert_failed_release` consults so a red
        gate re-hit inside the cooldown does not write a second releases row
        (each such row flips a project RED fleet-wide).
        """
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        rows = [{"to_sha": "staging-sha", "note": "[gate:qa] tests red",
                 "created_at": now}]

        with patch.object(release_train.db, "select", return_value=rows):
            assert release_train._recent_failed_gate("pareto-2080", "staging-sha", "qa") is True
            # A different gate, or a different SHA, is a different unit of work.
            assert release_train._recent_failed_gate("pareto-2080", "staging-sha", "build") is False
            assert release_train._recent_failed_gate("pareto-2080", "other-sha", "qa") is False

        with patch.object(release_train.db, "select", return_value=rows), \
                patch.object(release_train, "_recent_failed_gate", return_value=True) as guard:
            assert release_train._insert_failed_release(
                "pareto-2080", "qa", 3, "from", "staging-sha", "note") is None
            assert guard.called

    def test_merge_conflict_on_concurrent_attempt_detected(self):
        """Concurrent merge into same target is detected.

        Was: `self_healing_merge.attempt_merge(...)`, which does not exist.
        The module's real merge attempt is inside `_classify_files`, and a
        conflicting merge there is what produces the conflicting-file set.
        """
        with patch("self_healing_merge._git") as mock_git:
            mock_git.side_effect = [
                _cp([], 0, "base123\n"),
                _cp([], 0, "file.py\nother.py\n"),
                _cp([], 0),
                _cp([], 1, "", "CONFLICT (content): Merge conflict in file.py\n"),
                _cp([], 0), _cp([], 0), _cp([], 0),
            ]
            result = self_healing_merge._classify_files(
                "/repo", "relfix-pareto-2080", "orchestrator/dev")

        assert result["conflicting"] == ["file.py"]
        assert result["clean"] == ["other.py"]


class TestFallbackBehavior(unittest.TestCase):
    """Graceful degradation when healing fails."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    @patch("self_healing_merge._classify_files")
    def test_heal_failure_creates_repair_ticket(self, mock_classify):
        """Repair tickets accompany a successful partial heal, not a failed one.

        Was: asserted `result["fallback_repair_ticket_created"]` — a key the
        module never sets — from a heal whose classification raised. Substituted
        with the real contract: `_create_repair_tasks` is reached only once the
        clean files are actually merged, and it groups the conflicting files
        into one focused QUEUED task per directory.
        """
        mock_classify.return_value = {
            "clean": ["app/page.py"],
            "conflicting": ["auth/login.py", "auth/session.py", "billing/plan.py"],
            "all_changed": ["app/page.py", "auth/login.py", "auth/session.py",
                            "billing/plan.py"],
        }

        with patch.object(self_healing_merge, "_git", FakeGit()), \
                patch("auto_conflict_resolver.verify_merge", return_value=""), \
                patch.object(self_healing_merge, "_db") as mock_db:
            result = self_healing_merge.heal(
                repo=self.repo, branch="relfix-pareto-2080", base="master",
                project_id="pareto-2080")

        assert result["healed"] is True
        scopes = sorted(t["file_scope"] for t in result["repair_tasks"])
        assert scopes == ["auth/login.py, auth/session.py", "billing/plan.py"]
        assert mock_db.insert.call_count == 2

    @patch("self_healing_merge._classify_files")
    def test_heal_failure_branch_stays_conflict_for_manual_merge(self, mock_classify):
        """Failed heal leaves the branch untouched for the normal CONFLICT path.

        Was: made `_classify_files` return None (which no code path produces)
        and asserted a `result["state"]` key that does not exist. The real
        failure mode worth pinning is the one the module guards explicitly: a
        busy main checkout means an operator is mid-work there, so the merge is
        declined and the sub-branch is left for the merge train.
        """
        mock_classify.return_value = {
            "clean": ["clean.py"], "conflicting": ["conflict.py"],
            "all_changed": ["clean.py", "conflict.py"],
        }
        before = self_healing_merge.stats()["failed"]

        with patch.object(self_healing_merge, "_git",
                          FakeGit(head="some-agent-branch", dirty=" M runner/db.py\n")), \
                patch.object(self_healing_merge, "_db"):
            result = self_healing_merge.heal(
                repo=self.repo, branch="relfix-pareto-2080", base="master")

        assert result["healed"] is False
        assert result["merged"] == 0
        assert "main checkout busy" in result["reason"]
        assert "merge-train pickup" in result["reason"]
        assert self_healing_merge.stats()["failed"] == before + 1


class TestStatisticsTracking(unittest.TestCase):
    """Healing attempt statistics."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    def test_stats_track_successful_heals(self):
        """Stats increment on successful heal.

        Was: patched `self_healing_merge.db` (the handle is `_db`) and passed a
        one-file change set, which the MIN_FILES gate rejects before any heal
        is attempted — so the counter could never move.
        """
        before = self_healing_merge.stats()
        classification = {"clean": ["f.py", "g.py"], "conflicting": [],
                          "all_changed": ["f.py", "g.py"]}

        with patch.object(self_healing_merge, "_git", FakeGit()), \
                patch.object(self_healing_merge, "_classify_files",
                             return_value=classification), \
                patch.object(self_healing_merge, "_db"):
            result = self_healing_merge.heal(self.repo, "branch", "base")

        after = self_healing_merge.stats()
        assert result["healed"] is True
        assert after["healed"] == before["healed"] + 1
        assert after["attempted"] == before["attempted"] + 1

    def test_stats_track_partial_heals(self):
        """Stats track partial (clean merged, conflicts remain)."""
        before = self_healing_merge.stats()
        classification = {"clean": ["clean.py"], "conflicting": ["conflict.py"],
                          "all_changed": ["clean.py", "conflict.py"]}

        with patch.object(self_healing_merge, "_git", FakeGit()), \
                patch("auto_conflict_resolver.verify_merge", return_value=""), \
                patch.object(self_healing_merge, "_classify_files",
                             return_value=classification), \
                patch.object(self_healing_merge, "_db"):
            # base must be the branch the main checkout is on (FakeGit reports
            # "master"), or _create_sub_branch correctly declines to merge into
            # a checkout someone else is using.
            self_healing_merge.heal(self.repo, "branch", "master")

        after = self_healing_merge.stats()
        assert after["partial"] == before["partial"] + 1
        assert after["healed"] == before["healed"] + 1

    def test_stats_track_failed_heals(self):
        """Stats track attempts that fail.

        Was: made both `_git` and `_classify_files` raise, so `heal` propagated
        the exception and the assertion was never reached. `_classify_files` is
        fail-soft and cannot raise; the real "nothing to salvage" outcome is a
        change set with no clean files, which is counted as a failed attempt.
        """
        before = self_healing_merge.stats()
        classification = {"clean": [], "conflicting": ["a.py", "b.py"],
                          "all_changed": ["a.py", "b.py"]}

        with patch.object(self_healing_merge, "_git", FakeGit()), \
                patch.object(self_healing_merge, "_classify_files",
                             return_value=classification), \
                patch.object(self_healing_merge, "_db"):
            result = self_healing_merge.heal(self.repo, "branch", "base")

        after = self_healing_merge.stats()
        assert result["healed"] is False
        assert result["reason"] == "no clean files to extract"
        assert after["failed"] == before["failed"] + 1

    def test_stats_returns_a_snapshot_not_the_live_counter(self):
        """`stats()` hands back a copy, so a caller cannot corrupt the counters."""
        snapshot = self_healing_merge.stats()
        snapshot["healed"] = 10 ** 6
        assert self_healing_merge.stats()["healed"] != 10 ** 6


class TestEdgeCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    @patch("self_healing_merge._git")
    def test_empty_branch_no_changes_skips_healing(self, mock_git):
        """Branch with no changes is skipped."""
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, ""),          # no changed files
        ]

        result = self_healing_merge.heal(
            repo=self.repo, branch="empty-branch", base="master")

        assert result["healed"] is False
        assert "too few files" in result["reason"]

    def test_large_conflict_cluster_creates_multiple_repair_tasks(self):
        """Large conflict clusters are split into focused per-directory tasks.

        Was: patched a non-existent `_create_repair_task` and passed 20 files
        that all live in the repo root — which the real grouping (by directory)
        would correctly turn into ONE task, so the assertion described the
        opposite of the intended behaviour. Spread the cluster over directories
        and assert the split that actually makes the repair tasks "focused".
        """
        conflicting = ([f"api/route-{i}.py" for i in range(8)]
                       + [f"web/comp-{i}.py" for i in range(7)]
                       + ["README.md"])

        with patch.object(self_healing_merge, "_db") as mock_db:
            tasks = self_healing_merge._create_repair_tasks(
                conflicting, "agent/large-conflict", "pareto-2080")

        assert len(tasks) == 3
        by_slug = {t["slug"]: t for t in tasks}
        assert set(by_slug) == {"repair-large-conflict-api",
                                "repair-large-conflict-web",
                                "repair-large-conflict-root"}
        assert by_slug["repair-large-conflict-api"]["file_scope"].count(",") == 7
        assert by_slug["repair-large-conflict-root"]["file_scope"] == "README.md"
        assert all(len(t["slug"]) <= 60 for t in tasks)
        assert mock_db.insert.call_count == 3

    def test_unicode_in_filenames_handled_correctly(self):
        """Filenames with unicode survive classification and the sub-branch build.

        Was: patched `self_healing_merge.db` and ended in
        `assert isinstance(result, dict)` — a bare "does not crash". Assert the
        unicode paths actually make it through to the merge.
        """
        classification = {"clean": ["file_日本語.py", "ファイル.py"],
                          "conflicting": [],
                          "all_changed": ["file_日本語.py", "ファイル.py"]}
        fake_git = FakeGit()

        with patch.object(self_healing_merge, "_git", fake_git), \
                patch.object(self_healing_merge, "_classify_files",
                             return_value=classification), \
                patch.object(self_healing_merge, "_db"):
            result = self_healing_merge.heal(
                repo=self.repo, branch="unicode-branch", base="master")

        assert result["healed"] is True
        assert result["clean_files"] == ["file_日本語.py", "ファイル.py"]

    def test_release_train_gates_respect_red_gate_cooldown(self):
        """Red gate prevents re-running the same gate on the same SHA in cooldown.

        Was: `release_train.check_red_gate(project=..., cooldown_minutes=...)`,
        which does not exist. The real cooldown is `_recent_failed_gate`, keyed
        on (project, staging SHA, gate) and bounded by
        ORCH_RELEASE_RED_GATE_COOLDOWN_MIN.

        This rewrite surfaced a genuine bug, now fixed in release_train.py: a
        naive `created_at` (what `utcnow().isoformat()` and a `timestamp`
        column produce) raised TypeError against the tz-aware `now`, outside
        the function's try block.
        """
        recent = datetime.datetime.utcnow().isoformat()          # naive, as the DB returns
        stale = (datetime.datetime.utcnow()
                 - datetime.timedelta(minutes=release_train.RED_GATE_COOLDOWN_MIN + 30)
                 ).isoformat()

        with patch.object(release_train.db, "select", return_value=[
                {"to_sha": "sha-abc", "note": "[gate:qa] tests red",
                 "created_at": recent}]):
            assert release_train._recent_failed_gate("pareto-2080", "sha-abc", "qa") is True

        with patch.object(release_train.db, "select", return_value=[
                {"to_sha": "sha-abc", "note": "[gate:qa] tests red",
                 "created_at": stale}]):
            assert release_train._recent_failed_gate("pareto-2080", "sha-abc", "qa") is False


if __name__ == "__main__":
    unittest.main()
