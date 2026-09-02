"""
Comprehensive test suite for relfix-pareto-2080-07171927: Patch transplant with self-healing.

Task scope: adapt a proven prior patch for release-conflict self-healing in the
pareto-2080 project, under security-class constraints.

Test coverage:
- Patch similarity matching and transplant candidate selection
- Prior patch adaptation for pareto-2080 context
- Conflict detection and release branch decomposition
- Security validation gates (no credentials, transmission rules, custody gates)
- Orchestration pipeline contract compliance (model selection, executor capabilities)
- Deploy-cost rules enforcement (no direct prod pushes)
- Coordination rules (reuse solutions, don't overwrite queued work)
- Auto-merge coordination (orchestrator/dev staging, release train batch promotion)
- End-to-end workflow validation

NOTE ON THIS FILE'S HISTORY
---------------------------
Large parts of this suite were written against functions that do not exist:
`patch_templates.validate_security_gate` / `.validate_config_keys`,
`security_check.scan_for_hardcoded_secrets` / `.validate_config_keys_safe` /
`.scan_for_transmission_rule_violations` / `.check_custody_boundaries`,
`self_healing_merge.check_legal_gate` / `.can_proceed_with_merge`,
`release_train.automerge_after_qa` / `.can_push_branch` / `._target_branch`.
Two tests also read the module source from a hardcoded `/Users/kpasch/...`
path that only existed on one laptop, and the transplant tests assumed a 0.18
similarity floor that the fleet raised to 0.55 on purpose.

Every such test below now targets the function that really implements the
behaviour — `patch_transplant` (transplant + its fail-closed security gate),
`merged_diff_library` (retrieval, ranking and the secret-shape gate),
`config_sync._is_safe_key` (the ORCH_-prefix config rule), `legal_filter`
(owner/counsel approval), `self_healing_merge` and `release_train`. Where the
mapping is not one-to-one the substitution is explained in the test itself.
"""
import os
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config_sync
import legal_filter
import merged_diff_library
import patch_transplant
import release_train
import self_healing_merge

RUNNER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cp(args, returncode=0, stdout="", stderr=""):
    """CompletedProcess with `str` streams — what `_git` (text=True) really returns.

    Several tests here used to hand back `bytes`, so the module's `.splitlines()`
    produced bytes paths that could never equal the str paths it compares them to.
    """
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)


class FakeGit:
    """Stand-in for `self_healing_merge._git`, dispatching on the git subcommand.

    The module's call order is an implementation detail, so a positional
    side_effect list quietly answers the wrong command; dispatching on argv
    keeps each answer attached to the command it answers.
    """

    def __init__(self, head="master", dirty=""):
        self.calls = []
        self.head = head
        self.dirty = dirty

    def __call__(self, args, repo, timeout=None):
        self.calls.append((tuple(args), repo))
        sub = args[1] if len(args) > 1 else ""
        if sub == "-c":
            sub = "commit"
        if sub == "merge-base":
            return _cp(args, 0, "base123\n")
        if sub == "rev-parse":
            return _cp(args, 0, "presha123\n")
        if sub == "show":
            return _cp(args, 0, "content\n")
        if sub == "branch" and "--show-current" in args:
            return _cp(args, 0, self.head + "\n")
        if sub == "status":
            return _cp(args, 0, self.dirty)
        return _cp(args, 0, "")

    def argvs(self):
        return [c[0] for c in self.calls]


class TestPatchSimilarityMatching(unittest.TestCase):
    """Find and match prior patches by similarity threshold."""

    @patch("merged_diff_library.find")
    def test_find_prior_patch_above_minimum_threshold(self, mock_find):
        """A candidate above the fleet similarity floor becomes a transplant hint.

        Was: asserted that a 0.261 candidate clears "the 0.18 minimum". There is
        no 0.18 minimum any more, and that is the point — `transplant_discipline`
        documents at length that the two drifting floors (0.18 in hint(), 0.25 in
        find_transplant_source()) are what produced prompts like "adapt the proven
        patch beethoven/deployfix-... similarity=0.26", i.e. handing a coder an
        unrelated diff. One floor, 0.55, both doors. So: 0.261 must produce
        nothing, and a genuinely similar candidate must produce the hint.
        """
        mock_find.return_value = [{
            "project": "beethoven",
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.261,
            "summary": "Release conflict self-heal",
            "diff": "--- a/fleet_config.py\n+++ b/fleet_config.py\n",
        }]
        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict in pareto-2080",
            "project": "pareto-2080",
        }

        assert patch_transplant.hint(task) == ""

        mock_find.return_value[0]["similarity"] = 0.612
        hint = patch_transplant.hint(task)

        assert "PATCH TRANSPLANT" in hint
        assert "beethoven/deployfix-beethoven-07190257" in hint
        assert "0.612" in hint
        assert "Release conflict self-heal" in hint

    @patch("merged_diff_library.find")
    def test_skip_patch_below_minimum_threshold(self, mock_find):
        """Patch below the similarity floor is skipped."""
        mock_find.return_value = [{
            "project": "beethoven",
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.15,
            "diff": "...",
        }]

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict",
            "project": "pareto-2080",
        }

        hint = patch_transplant.hint(task)
        assert hint == ""

    @patch("merged_diff_library.find")
    def test_skip_when_patch_transplant_already_marked(self, mock_find):
        """Task already contains PATCH TRANSPLANT hint is not re-hinted."""
        mock_find.return_value = []

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "PATCH TRANSPLANT: before drafting...",
            "project": "pareto-2080",
        }

        hint = patch_transplant.hint(task)
        assert hint == ""
        assert not mock_find.called

    @patch("merged_diff_library.find")
    def test_return_empty_when_no_candidates_found(self, mock_find):
        """No candidates found returns empty hint."""
        mock_find.return_value = []

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix something novel",
            "project": "pareto-2080",
        }

        hint = patch_transplant.hint(task)
        assert hint == ""

    def test_highest_similarity_candidate_selected(self):
        """The most similar prior diff wins, and weak neighbours are dropped.

        Was: mocked `merged_diff_library.find` to return a pre-sorted list and
        then asserted `hint` reported list[0] — which only tested the mock's own
        ordering. Ranking is `find`'s job, so exercise `find` itself against the
        retrieval table, and confirm `hint` asks it for exactly one candidate
        rather than re-ranking.
        """
        task = {"id": "relfix-pareto", "project": "pareto-2080",
                "prompt": "release conflict staging decompose"}
        rows = [
            {"project": "beethoven", "slug": "weak-neighbour",
             "words": ["release", "conflict", "staging", "decompose",
                       "invoice", "stripe", "checkout", "webhook", "refund"],
             "prompt": "unrelated billing work", "diff": "weak"},
            {"project": "beethoven", "slug": "deployfix-beethoven-07190257",
             "words": ["release", "conflict", "staging", "decompose", "heal"],
             "prompt": "Release conflict self-heal", "diff": "strong"},
        ]

        with patch.object(merged_diff_library.db, "select", return_value=rows):
            hits = merged_diff_library.find(task, limit=3)

        assert [h["slug"] for h in hits] == ["deployfix-beethoven-07190257"]
        assert hits[0]["similarity"] >= merged_diff_library.similarity_floor()

        with patch.object(merged_diff_library, "find", return_value=hits) as mock_find:
            patch_transplant.hint(task)
        assert mock_find.call_args.kwargs == {"limit": 1}


class TestPatchAdaptation(unittest.TestCase):
    """Adapt proven patches for target project context."""

    def test_adapt_patch_preserves_core_changes(self):
        """Adapted patch retains the essential fix.

        Was: the "essential fix" in the fixture was `ORCH_SECURITY_GATE = True`,
        which `adapt_patch` refuses on purpose — a security change reviewed
        against one file must not be relocated to another. Assert the real
        contract: ordinary config changes survive adaptation intact, and the
        security-sensitive variant is refused.
        """
        prior_diff = (b"--- a/fleet_config.py\n"
                      b"+++ b/fleet_config.py\n"
                      b"@@ -5,3 +5,5 @@\n"
                      b" PROFILES = {}\n"
                      b"+ORCH_CONFLICT_AUTO_RESOLVE = True\n"
                      b"+ORCH_RELEASE_MIN_BATCH = 10\n")

        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"},
            target_files=["fleet_config.py"])

        assert b"ORCH_CONFLICT_AUTO_RESOLVE = True" in result
        assert b"ORCH_RELEASE_MIN_BATCH = 10" in result
        # The diff already targets fleet_config.py, so headers are left alone.
        assert b"--- a/fleet_config.py" in result

        sensitive = prior_diff.replace(b"ORCH_CONFLICT_AUTO_RESOLVE",
                                       b"ORCH_SECURITY_GATE")
        assert patch_transplant.adapt_patch(
            sensitive, target_task={"project": "pareto-2080"},
            target_files=["fleet_config.py"]) is None

    def test_adapt_patch_rewrites_paths_for_target(self):
        """Patch paths are rewritten to match target project structure."""
        prior_diff = (b"--- a/runner/fleet_config.py\n"
                      b"+++ b/runner/fleet_config.py\n"
                      b"@@ -1,3 +1,5 @@\n"
                      b" import os\n"
                      b"+PARETO_PROFILE = 'batch'\n")

        result = patch_transplant.adapt_patch(
            prior_diff,
            target_task={"project": "pareto-2080"},
            target_files=["pareto_2080_config.py"])

        # Was: `assert result is not None` plus a "# Should handle path
        # rewriting" comment that asserted nothing. Assert the rewrite.
        assert b"--- a/pareto_2080_config.py" in result
        assert b"+++ b/pareto_2080_config.py" in result
        assert b"runner/fleet_config.py" not in result
        assert b"+PARETO_PROFILE = 'batch'" in result

    def test_adapt_patch_handles_string_input(self):
        """String-type diffs come back as strings; bytes come back as bytes."""
        prior_diff = ("--- a/config.py\n"
                      "+++ b/config.py\n"
                      "@@ -1 +1,2 @@\n"
                      " x = 1\n"
                      "+y = 2\n")

        result = patch_transplant.adapt_patch(
            prior_diff, target_task={"project": "pareto-2080"})

        # Was: `assert result is not None` with a "# Should handle string/bytes
        # conversion" comment. The conversion is the claim, so check it.
        assert isinstance(result, str)
        assert result == prior_diff
        assert isinstance(
            patch_transplant.adapt_patch(prior_diff.encode(), {"project": "p"}), bytes)

    def test_adapt_patch_security_gate_preserved_for_pareto(self):
        """A patch touching ORCH_PIPELINE_SECURITY_GATE is refused, not relocated.

        Was: expected the gate line to be "preserved" in the adapted output.
        That is precisely the bug the module records fixing on 2026-08-11 — the
        check used to be `if <condition>: pass`, so every security-sensitive
        patch was transplanted as if no check existed. The gate is fail-closed:
        it returns None and logs the offending token.
        """
        prior_diff = (b"--- a/fleet_config.py\n"
                      b"+++ b/fleet_config.py\n"
                      b"@@ -1,3 +1,6 @@\n"
                      b" PROFILES = {}\n"
                      b"+ORCH_PIPELINE_SECURITY_GATE = True\n"
                      b"+# Security validation required for release\n")

        assert patch_transplant.security_findings(prior_diff) == \
            ["ORCH_PIPELINE_SECURITY_GATE"]
        with patch.object(patch_transplant.log, "warning") as warn:
            result = patch_transplant.adapt_patch(
                prior_diff, target_task={"project": "pareto-2080"})

        assert result is None
        assert "ORCH_PIPELINE_SECURITY_GATE" in str(warn.call_args)

    def test_adapt_patch_returns_none_for_empty_prior_diff(self):
        """Empty or None prior diff returns None."""
        assert patch_transplant.adapt_patch(None, {"project": "pareto-2080"}) is None
        # Was: called with b"" and asserted nothing ("# Empty should be handled
        # gracefully"). Empty input is falsy, so it takes the same early return.
        assert patch_transplant.adapt_patch(b"", {"project": "pareto-2080"}) is None
        assert patch_transplant.adapt_patch("", {"project": "pareto-2080"}) is None


class TestPatchApplication(unittest.TestCase):
    """Apply transplanted patches to repository."""

    @patch("subprocess.run")
    def test_apply_patch_dry_run_succeeds(self, mock_run):
        """Dry-run succeeds when patch applies cleanly."""
        patch_diff = (b"--- a/test.py\n"
                      b"+++ b/test.py\n"
                      b"@@ -1,3 +1,4 @@\n"
                      b" def foo():\n"
                      b"+    pass\n")
        mock_run.return_value = Mock(returncode=0, stdout=b"", stderr=b"")

        result = patch_transplant.apply_patch(patch_diff, repo_path="/repo")

        assert result["applied"] is True
        assert result["rejects"] == 0
        assert [c.args[0] for c in mock_run.call_args_list] == [
            ["patch", "--dry-run", "-p1"], ["patch", "-p1"]]

    @patch("subprocess.run")
    def test_apply_patch_with_rejects_detects_conflicts(self, mock_run):
        """Patch application with rejects is detected."""
        patch_diff = b"--- a/test.py\n+++ b/test.py\n"
        mock_run.side_effect = [
            Mock(returncode=1, stdout=b"", stderr=b"FAILED: conflict\n")
        ]

        result = patch_transplant.apply_patch(
            patch_diff, repo_path="/repo", allow_rejects=False)

        assert result["applied"] is False
        assert result["rejects"] > 0
        assert result["fallback_rebuild"] is True
        # A failed dry run must not be followed by a real apply.
        assert mock_run.call_count == 1

    @patch("subprocess.run")
    def test_apply_patch_timeout_triggers_fallback(self, mock_run):
        """Patch application timeout triggers rebuild fallback."""
        patch_diff = b"--- a/test.py\n"
        mock_run.side_effect = subprocess_timeout_error()

        result = patch_transplant.apply_patch(patch_diff, repo_path="/repo")

        assert result["applied"] is False
        assert result["fallback_rebuild"] is True

    @patch("subprocess.run")
    def test_apply_patch_handles_bytes_input(self, mock_run):
        """Bytes patch input is fed straight to `patch` on stdin."""
        patch_diff = b"--- a/file.py\n+++ b/file.py\n"
        mock_run.return_value = Mock(returncode=0, stdout=b"")

        result = patch_transplant.apply_patch(patch_diff, repo_path="/repo")

        # Was: no assertion at all ("# Should not crash on bytes input").
        assert result["applied"] is True
        assert mock_run.call_args_list[0].kwargs["input"] == patch_diff
        assert mock_run.call_args_list[0].kwargs["cwd"] == "/repo"

    def test_apply_patch_none_input_returns_fallback(self):
        """None patch triggers fallback rebuild."""
        result = patch_transplant.apply_patch(None, repo_path="/repo")

        assert result["applied"] is False
        assert result["fallback_rebuild"] is True


class TestConflictDetectionAndClassification(unittest.TestCase):
    """Release conflict detection and file classification.

    `_classify_files` issues, in order: merge-base, diff --name-only,
    worktree add --detach, merge --no-commit --no-ff (in the worktree), then
    merge --abort / worktree remove / worktree prune. There is no "checkout
    base" step and no second `diff --name-only` for the conflict set — conflicts
    are parsed out of git's own merge output.
    """

    @patch("self_healing_merge._git")
    def test_classify_release_branch_clean_merge(self, mock_git):
        """Release branch with no conflicts classifies files as all clean."""
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),                     # merge-base
            _cp([], 0, "config.py\nrunner.py\n"),        # diff --name-only
            _cp([], 0),                                  # worktree add --detach
            _cp([], 0),                                  # merge succeeds
            _cp([], 0), _cp([], 0), _cp([], 0),          # abort/remove/prune
        ]

        result = self_healing_merge._classify_files(
            "/repo", "release/pareto-2080", "master")

        assert result["clean"] == ["config.py", "runner.py"]
        assert result["conflicting"] == []

    @patch("self_healing_merge._git")
    def test_classify_release_branch_partial_conflict(self, mock_git):
        """Some files clean, some conflicting (classic partial release conflict)."""
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, "safe1.py\nsafe2.py\nrelease_config.py\n"),
            _cp([], 0),
            _cp([], 1, "", "CONFLICT (content): Merge conflict in release_config.py\n"
                           "Automatic merge failed; fix conflicts.\n"),
            _cp([], 0), _cp([], 0), _cp([], 0),
        ]

        result = self_healing_merge._classify_files(
            "/repo", "release/pareto-2080", "master")

        assert result["clean"] == ["safe1.py", "safe2.py"]
        assert result["conflicting"] == ["release_config.py"]

    @patch("self_healing_merge._git")
    def test_classify_merge_failure_without_conflicts_is_not_clean(self, mock_git):
        """A merge that fails without naming a conflict is NOT "all clean".

        This test found a real bug, now fixed in self_healing_merge.py: "clean"
        was computed as "not named in the conflict output", so a merge that
        failed for any non-conflict reason (a 90s timeout -> returncode 124, a
        locked index, a hook refusal) produced an empty conflict set and marked
        every changed file clean. heal() then reported "no conflicts found
        (branch may be mergeable)" with healed=True and merged=0, which
        continuous_merger logs as a successful self-heal.
        """
        mock_git.side_effect = [
            _cp([], 0, "base123\n"),
            _cp([], 0, "a.py\nb.py\n"),
            _cp([], 0),
            _cp([], 124, "", "timeout"),
            _cp([], 0), _cp([], 0), _cp([], 0),
        ]

        result = self_healing_merge._classify_files("/repo", "feature", "master")

        assert result["clean"] == []
        assert result["conflicting"] == ["a.py", "b.py"]


class TestSecurityValidationGates(unittest.TestCase):
    """Security gate enforcement for the pareto-2080 security-class task.

    `patch_templates.validate_security_gate` / `.validate_config_keys` and the
    `security_check.*` scanners this class mocked do not exist — `security_check`
    is a scanner for tracked `.claude/settings.local.json` files, nothing to do
    with merges. The gates that really stand in front of a transplant are
    `patch_transplant.security_findings` (token shapes on ADDED lines),
    `merged_diff_library.contains_secret` / `adapt_diff` (credential *values*,
    dropped whole) and `config_sync._is_safe_key` (the ORCH_-prefix rule).
    """

    def test_security_gate_blocks_hardcoded_api_keys(self):
        """A diff that hardcodes a credential value is dropped, not sanitised."""
        source_diff = (
            "diff --git a/fleet_config.py b/fleet_config.py\n"
            "--- a/fleet_config.py\n"
            "+++ b/fleet_config.py\n"
            "@@ -1,2 +1,3 @@\n"
            " PROFILES = {}\n"
            '+AWS = "AKIAIOSFODNN7EXAMPLE"\n')

        assert merged_diff_library.contains_secret(source_diff) is True

        adapted = merged_diff_library.adapt_diff(
            {"project": "pareto-2080"}, source_diff,
            target_files=["pareto_2080_config.py"])

        assert adapted["secrets_blocked"] == 1
        assert adapted["patch"] == ""
        assert adapted["dropped"] == [("fleet_config.py", "secret-shape refused")]

    def test_security_gate_requires_orch_prefix_for_fleet_config(self):
        """Fleet-wide config keys must be ORCH_-prefixed AND carry no secret marker.

        `config_sync._is_safe_key` is the rule: a key is pushed fleet-wide only
        if it starts with an approved prefix and contains none of
        KEY/SECRET/TOKEN/PASSWORD/PWD/CREDENTIAL.
        """
        assert config_sync._is_safe_key("ORCH_RELEASE_MIN_BATCH") is True
        assert config_sync._is_safe_key("RELEASE_INTERVAL_HOURS") is True

        assert config_sync._is_safe_key("SECRET_TOKEN") is False      # no safe prefix
        assert config_sync._is_safe_key("FLEET_MODE") is False        # no safe prefix
        # The prefix alone is not enough: a secret marker disqualifies the key.
        assert config_sync._is_safe_key("ORCH_SECRET_TOKEN") is False
        assert config_sync._is_safe_key("ORCH_API_KEY") is False

    def test_security_gate_blocks_transmission_rule_violations(self):
        """Credential transmission added by a patch blocks the transplant."""
        diff = ("--- a/transport.py\n"
                "+++ b/transport.py\n"
                "@@ -1,2 +1,4 @@\n"
                " import requests\n"
                '+headers = {"Authorization": SERVICE_ACCESS_TOKEN}\n'
                '+requests.post("http://relay.internal", headers=headers)\n')

        findings = patch_transplant.security_findings(diff)

        assert findings
        assert {f.lower() for f in findings} <= {"authorization", "access_token"}
        assert patch_transplant.adapt_patch(diff, {"project": "pareto-2080"}) is None

    def test_security_gate_protects_data_custody_rules(self):
        """Work that changes the data/funds custody posture needs owner approval.

        Substituted for a `security_check.check_custody_boundaries` that does not
        exist; `legal_filter.requires_owner_approval` is the repo's one narrow
        custody/licensing predicate.
        """
        custody = ("Change pareto-2080 payouts so the platform will hold customer "
                   "funds in a custodial account before disbursement.")
        routine = "Add structured logging around the payout retry loop."

        assert legal_filter.requires_owner_approval(text=custody) is True
        assert legal_filter.requires_owner_approval(text=routine) is False


class TestLegalGateChecking(unittest.TestCase):
    """Legal gate for licensing, registration, custody changes.

    `self_healing_merge.check_legal_gate` never existed. `legal_filter`
    judges the description of the work rather than a list of changed filenames,
    which is what its owner policy actually says: gate only when the work would
    change the company's regulatory posture.
    """

    def test_legal_gate_owner_only_licensing_changes(self):
        """Work that would force licensing/registration requires the owner."""
        text = ("relfix-pareto-2080: add a money transmission path; this "
                "requires the company to obtain a money transmitter license "
                "and register as an MSB.")

        assert legal_filter.requires_owner_approval(text=text) is True
        assert legal_filter.trigger_excerpt(text=text)

    def test_legal_gate_normal_code_change_passes(self):
        """Normal code changes pass legal gate."""
        text = "Refactor runner.py and db.py to share one retry helper."

        assert legal_filter.requires_owner_approval(text=text) is False

    def test_legal_gate_does_not_gate_on_generic_regulatory_smell(self):
        """Preserving the legal posture is not changing it.

        The module's stated owner policy: do not stop implementation for generic
        "regulatory" smell — safe-positioning language means the task keeps the
        strategy rather than changing it.
        """
        text = ("Add a disclaimer so the custody comparison stays informational "
                "and non-custodial; we hold no customer funds.")

        assert legal_filter.requires_owner_approval(text=text) is False


class TestOrchestrationPipelineComplianceContract(unittest.TestCase):
    """Verify orchestration pipeline contract compliance."""

    def test_orchestration_contract_specifies_correct_triage_model(self):
        """Task uses deepseek for triage (vs local/google models)."""
        contract = {
            "source": "release-conflict-self-heal",
            "project": "pareto-2080",
            "task_class": "security",
            "preflight_triage": "local:deepseek-coder-v2:16b"
        }

        # Contract must specify expected triage model
        assert "deepseek" in contract["preflight_triage"].lower() or "local" in contract["preflight_triage"]

    def test_orchestration_contract_specifies_strategy_planner(self):
        """Task uses deepseek for strategy planning."""
        contract = {
            "strategy_planner": "deepseek:deepseek-v4-pro",
            "qpd_leader_quality": 7.4,
            "qpd_leader_cost": "$0.0"
        }

        assert "deepseek" in contract["strategy_planner"].lower()

    def test_orchestration_contract_specifies_agentic_coder(self):
        """Task uses claude-sonnet-4-6 for code generation."""
        contract = {
            "agentic_coder": "claude using author model claude-sonnet-4-6",
            "required_executor_capabilities": ["code_generation", "text_completion"]
        }

        assert "claude" in contract["agentic_coder"].lower()
        assert "code_generation" in contract["required_executor_capabilities"]

    def test_orchestration_contract_qa_route(self):
        """QA uses independent route with diverse panel."""
        contract = {
            "independent_qa_route": "deepseek:deepseek-v4-flash",
            "qa_panel": ["local:llama3.2:3b", "deepseek:deepseek-v4-flash"]
        }

        assert len(contract["qa_panel"]) >= 2
        # Should have diversity (local + cloud models)


class TestDeployCostRuleEnforcement(unittest.TestCase):
    """Deploy-cost rules: never direct prod deploy."""

    RELEASE_TRAIN_PY = os.path.join(RUNNER_DIR, "release_train.py")

    def _promotion_git_calls(self, push_rc=0):
        """Drive the real prod-promotion path and record every git argv it runs."""
        calls = []

        def fake_git(repo, *args, timeout=None):
            calls.append(args)
            if args[0] == "rev-parse":
                return _cp(list(args), 0, "integrated-sha\n")
            if args[0] == "push":
                return _cp(list(args), push_rc, "", "" if push_rc == 0 else "rejected")
            return _cp(list(args), 0, "")

        project = {"id": "p1", "name": "pareto-2080"}
        with patch.object(release_train, "_git", side_effect=fake_git), \
                patch.object(release_train, "_integrate_prod_into_staging",
                             return_value=(True, "ok", "integrated-sha", False)), \
                patch.object(release_train, "_persist_production_build_proof",
                             return_value=(True, "")), \
                patch.object(release_train.delivery_lease, "require",
                             return_value=None), \
                patch.object(release_train.shadow_mode, "refuse", return_value=False), \
                patch.object(release_train, "_insert_failed_release", return_value=None), \
                patch.object(release_train, "_self_heal_release_conflict",
                             return_value=None):
            pushed, to_sha, log = release_train._integrate_regate_and_push(
                project, "pareto-2080", "/repo", "master", 12, "base-sha",
                "staging-sha", "npm test", False, "npm run build", attempts=1)
        return pushed, to_sha, calls

    def test_never_run_vercel_prod_command(self):
        """`vercel --prod` never appears in the release path.

        Was: opened `/Users/kpasch/Documents/beethoven/claude-orchestrator/
        runner/release_train.py`, a path that exists on exactly one laptop, so
        the test could only ever raise FileNotFoundError anywhere else. Read the
        module that is actually under test.
        """
        with open(self.RELEASE_TRAIN_PY, encoding="utf-8") as f:
            deploy_code = f.read()

        for cmd in ("vercel --prod", "vercel deploy --prod"):
            assert cmd not in deploy_code, f"Forbidden command '{cmd}' found in deploy code"
        # Prod moves by pushing the staging branch; deploy_verify watches the build.
        assert 'f"{STAGING}:{prod}"' in deploy_code

    def test_never_push_main_master_directly(self):
        """Promotion pushes staging onto prod, and never forces.

        Was: a source-text `assert "batch" in code.lower() or "staging" in
        code.lower()`, which is true of almost any release module. Drive the real
        promotion instead and inspect the git command it issues.
        """
        pushed, to_sha, calls = self._promotion_git_calls()

        pushes = [a for a in calls if a[0] == "push"]
        assert pushed is True
        assert to_sha == "integrated-sha"
        assert pushes == [("push", "origin", f"{release_train.STAGING}:master")]
        assert not any("--force" in a or "--force-with-lease" in a for a in calls)
        # The prod branch is never checked out or reset to make the push fit.
        assert not any(a[0] in ("checkout", "reset") for a in calls)

    def test_push_only_task_branch_for_batch_train(self):
        """Agent branches reach staging only; the train promotes, they do not.

        Was: `release_train.can_push_branch("relfix-...") is True` /
        `can_push_branch("master") is False` — no such function. The rule is
        structural: `_merge_into_staging` is the only door an agent branch has,
        it merges into STAGING inside an ephemeral worktree, and it pushes
        nothing at all.
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
            merged = release_train._merge_into_staging(
                "/repo", "relfix-pareto-2080-07171927")

        assert merged is True
        assert git_calls[0][:3] == ("worktree", "add", "-f")
        assert git_calls[0][-1] == release_train.STAGING
        assert not any(a[0] == "push" for a in git_calls)
        assert not any(r[:2] == ["git", "push"] for r in recorded)


class TestCoordinationRuleEnforcement(unittest.TestCase):
    """Coordination rules: reuse solutions, don't delete queued work."""

    @patch("merged_diff_library.find")
    def test_reuse_proven_prior_solutions_first(self, mock_find):
        """Proven prior solutions are reused before drafting new code."""
        mock_find.return_value = [{
            "project": "beethoven",
            "slug": "deployfix-beethoven-07190257",
            "similarity": 0.612,       # above the 0.55 fleet floor; 0.261 was not
            "summary": "Release conflict self-heal",
            "diff": "--- a/release_train.py\n+++ b/release_train.py\n",
        }]

        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict",
            "project": "pareto-2080",
        }

        hint = patch_transplant.hint(task)

        assert "PATCH TRANSPLANT" in hint
        assert "before drafting from scratch" in hint
        assert "beethoven/deployfix-beethoven-07190257" in hint

    def test_coordination_rule_dont_overwrite_unrelated_queued_tasks(self):
        """Repair-task creation only ever INSERTS; queued work is never touched.

        Was: called `self_healing_merge.can_proceed_with_merge(...)`, which does
        not exist, and then asserted nothing at all ("# Implementation detail:
        verify coordinator doesn't call destructive ops"). The coordinator whose
        behaviour matters here is `_create_repair_tasks`, the one place this
        module writes to the tasks table — so assert it inserts and does nothing
        else.
        """
        with patch.object(self_healing_merge, "_db") as mock_db:
            tasks = self_healing_merge._create_repair_tasks(
                ["api/route.py"], "relfix-pareto-2080-07171927", "pareto-2080")

        assert len(tasks) == 1
        assert mock_db.insert.call_count == 1
        assert mock_db.insert.call_args[0][0] == "tasks"
        assert mock_db.insert.call_args[0][1]["state"] == "QUEUED"
        for destructive in ("delete", "update", "upsert", "execute"):
            assert not getattr(mock_db, destructive).called, destructive

    def test_repair_task_creation_is_fail_soft_on_db_errors(self):
        """A tasks-table write that fails must not take the heal down."""
        with patch.object(self_healing_merge, "_db") as mock_db:
            mock_db.insert.side_effect = RuntimeError("db down")
            tasks = self_healing_merge._create_repair_tasks(
                ["api/route.py"], "relfix-pareto-2080", "pareto-2080")

        assert tasks == []


class TestAutoMergeToStagingBranch(unittest.TestCase):
    """Auto-merge to orchestrator/dev after tests pass.

    `release_train.automerge_after_qa` and `._target_branch` do not exist. The
    real merge of a gate-passed branch into staging is `_merge_into_staging`,
    which returns a bool, targets the module-level STAGING branch, and runs its
    own fail-closed anti-loss gate before accepting the merge.
    """

    def _merge(self, merge_rc=0, verify=""):
        recorded = []

        def fake_run(args, **kwargs):
            recorded.append(list(args))
            if "rev-parse" in args:
                return _cp(args, 0, "presha123\n")
            if "merge" in args and "--abort" not in args:
                return _cp(args, merge_rc, "",
                           "" if merge_rc == 0
                           else "CONFLICT (content): Merge conflict in x.py\n")
            return _cp(args, 0)

        git_calls = []

        def fake_git(repo, *args, timeout=None):
            git_calls.append(args)
            return _cp(list(args), 0)

        with patch.object(release_train, "_git", side_effect=fake_git), \
                patch("subprocess.run", side_effect=fake_run), \
                patch("auto_conflict_resolver.verify_merge", return_value=verify):
            merged = release_train._merge_into_staging(
                "/repo", "relfix-pareto-2080-07171927")
        return merged, recorded, git_calls

    def test_automerge_after_all_qa_gates_pass(self):
        """A gate-passed branch merges into staging."""
        merged, recorded, _ = self._merge()

        assert merged is True
        assert ["git", "merge", "--no-ff", "-m",
                "train: relfix-pareto-2080-07171927",
                "relfix-pareto-2080-07171927"] in recorded

    def test_automerge_blocked_if_security_gate_fails(self):
        """A merge the anti-loss gate flags is rolled back, not staged.

        Was: expected `automerge_after_qa` to read a "security_gate" column and
        return a reason. The real fail-closed verdict on this path is
        `auto_conflict_resolver.verify_merge`; on findings staging is reset to
        the pre-merge SHA and the merge is refused.
        """
        merged, recorded, _ = self._merge(
            verify="discard: fleet_config.py loses ORCH_PIPELINE_SECURITY_GATE")

        assert merged is False
        assert ["git", "reset", "--hard", "presha123"] in recorded

    def test_automerge_to_correct_staging_branch(self):
        """Auto-merge targets the orchestrator/dev staging branch."""
        merged, _, git_calls = self._merge()

        assert release_train.STAGING == "orchestrator/dev"
        assert merged is True
        worktree_add = [a for a in git_calls if a[:2] == ("worktree", "add")]
        assert worktree_add and worktree_add[0][-1] == "orchestrator/dev"


class TestReleaseTrainBatchCoordination(unittest.TestCase):
    """Release train batch coordination and cadence gates."""

    def test_batch_minimum_not_met_holds_release(self):
        """Release held when ahead count < batch minimum."""
        assert release_train._release_decision(ahead=5, due=False, minimum=10) == "hold"

    def test_batch_full_triggers_release(self):
        """Release triggered when ahead >= batch minimum."""
        assert release_train._release_decision(ahead=15, due=False, minimum=10) == "release"

    def test_cadence_due_flushes_partial_batch(self):
        """Cadence timeout flushes partial batch."""
        assert release_train._release_decision(ahead=7, due=True, minimum=10) == "release"


class TestEndToEndWorkflow(unittest.TestCase):
    """Complete workflow: detect conflict -> transplant patch -> heal -> auto-merge."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    def test_complete_relfix_pareto_2080_workflow(self):
        """Hint -> partial heal -> staging merge, with only git/db at the edges.

        Was: patched `patch_transplant.hint`, `self_healing_merge.heal` and a
        non-existent `release_train.automerge_after_qa`, then called those three
        mocks and asserted their return values — the workflow under test was
        entirely fictional. Each stage below now runs the real function.
        """
        task = {
            "id": "relfix-pareto-2080-07171927",
            "prompt": "Fix release conflict in pareto-2080 staging decompose",
            "project": "pareto-2080",
        }

        # Step 1: a sufficiently similar prior diff becomes a transplant hint.
        with patch.object(merged_diff_library, "find", return_value=[{
                "project": "beethoven", "slug": "deployfix-beethoven-07190257",
                "similarity": 0.612, "summary": "Release conflict self-heal",
                "diff": "--- a/release_train.py\n+++ b/release_train.py\n"}]):
            hint = patch_transplant.hint(task)
        assert "PATCH TRANSPLANT" in hint
        assert "deployfix-beethoven-07190257" in hint

        # Step 2: heal the conflicting branch — clean files land, the rest
        # become a focused repair task.
        classification = {
            "clean": ["api/route.py"],
            "conflicting": ["fleet_config.py"],
            "all_changed": ["api/route.py", "fleet_config.py"],
        }
        with patch.object(self_healing_merge, "_git", FakeGit()), \
                patch.object(self_healing_merge, "_classify_files",
                             return_value=classification), \
                patch("auto_conflict_resolver.verify_merge", return_value=""), \
                patch.object(self_healing_merge, "_db") as mock_db:
            heal_result = self_healing_merge.heal(
                repo=self.repo, branch=task["id"], base="master",
                project_id="pareto-2080")

        assert heal_result["healed"] is True
        assert heal_result["merged"] == 1
        assert [t["file_scope"] for t in heal_result["repair_tasks"]] == ["fleet_config.py"]
        assert mock_db.insert.called

        # Step 3: the healed branch merges into the staging branch.
        def fake_run(args, **kwargs):
            if "rev-parse" in args:
                return _cp(args, 0, "presha123\n")
            return _cp(args, 0)

        with patch.object(release_train, "_git", return_value=_cp([], 0)), \
                patch("subprocess.run", side_effect=fake_run), \
                patch("auto_conflict_resolver.verify_merge", return_value=""):
            assert release_train._merge_into_staging("/repo", task["id"]) is True


class TestErrorHandlingAndFallbacks(unittest.TestCase):
    """Graceful degradation on errors."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    @patch("subprocess.run")
    def test_patch_apply_failure_triggers_fallback_rebuild(self, mock_run):
        """Patch application failure triggers local rebuild.

        Was: patched `patch_transplant.apply_patch` and then called it, so the
        assertion only checked the mock's own return value. Run the real
        function against a failing `patch` process instead.
        """
        mock_run.return_value = Mock(
            returncode=1, stdout=b"",
            stderr=b"1 out of 3 hunks FAILED -- saving rejects to file x.py.rej\n")

        result = patch_transplant.apply_patch(
            b"--- a/x.py\n+++ b/x.py\n", repo_path="/repo", allow_rejects=False)

        assert result["applied"] is False
        assert result["rejects"] >= 1
        assert result["fallback_rebuild"] is True

    def test_conflict_classification_timeout_creates_repair_ticket(self):
        """A git timeout during classification leaves the branch to the repair path.

        Was: made `_classify_files` raise TimeoutError (it is fail-soft and
        cannot) and asserted `result["fallback_repair_ticket_created"]`, a key
        heal() never sets. The real timeout path is `_git` returning 124: the
        change set is classified as entirely conflicting, so there is nothing to
        merge, no repair task is created (tasks accompany work that landed), and
        the attempt is counted as failed — which leaves the branch CONFLICT for
        continuous_merger's normal handling.
        """
        before = self_healing_merge.stats()["failed"]
        timeout_seq = [
            _cp([], 0, "base123\n"),
            _cp([], 0, "a.py\nb.py\n"),
            _cp([], 0),
            _cp([], 124, "", "timeout"),
            _cp([], 0), _cp([], 0), _cp([], 0),
        ]

        with patch.object(self_healing_merge, "_git", side_effect=timeout_seq), \
                patch.object(self_healing_merge, "_db") as mock_db:
            result = self_healing_merge.heal(
                repo=self.repo, branch="relfix-pareto-2080-07171927", base="master")

        assert result["healed"] is False
        assert result["reason"] == "no clean files to extract"
        assert result["conflicting_files"] == ["a.py", "b.py"]
        assert not mock_db.insert.called
        assert self_healing_merge.stats()["failed"] == before + 1


class TestSpecialCases(unittest.TestCase):
    """Edge cases and boundary conditions."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = self.temp_dir.name
        self.worktree_root = self.repo + "-wt"

    def tearDown(self):
        shutil.rmtree(self.worktree_root, ignore_errors=True)
        self.temp_dir.cleanup()

    def test_pareto_2080_specific_config_preservation(self):
        """Project-specific config survives adaptation — unless it is a security gate.

        Was: asserted that a diff adding `ORCH_PARETO_2080_SECURITY_GATE` came
        back containing "pareto". It comes back as None: the fail-closed gate
        matches `ORCH_[A-Z0-9_]*SECURITY_GATE` by design, precisely so a
        reviewed gate change cannot be relocated into another project's file.
        """
        gated = (b"--- a/config.py\n"
                 b"+++ b/config.py\n"
                 b"@@ -1,3 +1,5 @@\n"
                 b" PROJECTS = ['pareto-2080', 'beethoven']\n"
                 b"+ORCH_PARETO_2080_SECURITY_GATE = True\n")

        assert patch_transplant.security_findings(gated) == \
            ["ORCH_PARETO_2080_SECURITY_GATE"]
        assert patch_transplant.adapt_patch(
            gated, target_task={"project": "pareto-2080"}) is None

        # The ordinary project config in the same shape is preserved verbatim.
        ordinary = gated.replace(b"ORCH_PARETO_2080_SECURITY_GATE = True",
                                 b"ORCH_PARETO_2080_RELEASE_BATCH = 10")
        adapted = patch_transplant.adapt_patch(
            ordinary, target_task={"project": "pareto-2080"})
        assert b"ORCH_PARETO_2080_RELEASE_BATCH = 10" in adapted
        assert b"pareto-2080" in adapted

    def test_very_large_conflict_cluster_creates_focused_repair_tasks(self):
        """Large conflict clusters split into one focused task per directory.

        Was: patched a `_create_repair_task` that does not exist and asserted
        nothing ("# Should handle large clusters"). The real grouping key is the
        file's directory, which is what makes a repair task "focused"; 15 files
        in one directory is deliberately ONE task, not fifteen.
        """
        conflicting = ([f"api/handler-{i}.py" for i in range(15)]
                       + [f"web/view-{i}.py" for i in range(5)]
                       + ["CHANGELOG.md"])

        with patch.object(self_healing_merge, "_db") as mock_db:
            tasks = self_healing_merge._create_repair_tasks(
                conflicting, "agent/relfix-pareto-2080-07171927", "pareto-2080")

        by_slug = {t["slug"]: t for t in tasks}
        assert len(tasks) == 3
        assert set(by_slug) == {"repair-relfix-pareto-2080-07171927-api",
                                "repair-relfix-pareto-2080-07171927-web",
                                "repair-relfix-pareto-2080-07171927-root"}
        api = by_slug["repair-relfix-pareto-2080-07171927-api"]
        assert api["file_scope"].count(",") == 14
        assert "api/handler-0.py" in api["prompt"]
        assert "agent/relfix-pareto-2080-07171927" in api["prompt"]
        assert all(len(t["slug"]) <= 60 for t in tasks)
        assert mock_db.insert.call_count == 3


def subprocess_timeout_error():
    """Helper to raise subprocess timeout."""
    import subprocess
    return subprocess.TimeoutExpired("patch", 30)


if __name__ == "__main__":
    unittest.main()
