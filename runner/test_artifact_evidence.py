"""Tests for runner/artifact_evidence.py (P1 — artifact_commit fanout).

The measured facts these encode: 47f26779 (2 files changed) is the claimed
artifact of 32 distinct tasks; a two-file commit cannot be the deliverable of 32
tasks, so a shared commit is evidence for a task only when it touches that
task's declared scope.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import artifact_evidence as ev  # noqa: E402


class _FakeGit:
    """Injectable git: maps sha -> changed files. Unknown shas do not resolve."""

    class R:
        def __init__(self, rc, out=""):
            self.returncode = rc
            self.stdout = out

    def __init__(self, commits):
        self.commits = commits

    def __call__(self, argv):
        sha = argv[-1].replace("^{commit}", "")
        if "cat-file" in argv:
            return self.R(0 if sha in self.commits else 1)
        if "show" in argv:
            if sha not in self.commits:
                return self.R(1)
            return self.R(0, "\n".join(self.commits[sha]) + "\n")
        return self.R(1)


TWO_FILE = "47f26779ebe654b491d211769c7456f074e187ad"
GIT = _FakeGit({TWO_FILE: ["runner/merge_train.py", "runner/verify.py"]})


class CitationTests(unittest.TestCase):
    def test_canonical_form_round_trips(self):
        cite = ev.format_citation("beethoven", TWO_FILE)
        self.assertEqual(cite, "beethoven@" + TWO_FILE)
        self.assertEqual(ev.parse_citation(cite), ("beethoven", TWO_FILE, True))

    def test_bare_sha_parses_but_is_not_repo_known(self):
        repo, sha, known = ev.parse_citation(TWO_FILE)
        self.assertEqual(repo, "")
        self.assertEqual(sha, TWO_FILE)
        self.assertFalse(known, "a bare sha is unverifiable by construction (R2)")

    def test_repo_less_citation_is_refused_by_formatter(self):
        self.assertEqual(ev.format_citation("", TWO_FILE), "")

    def test_garbage_and_empty_are_fail_soft(self):
        for value in (None, "", "   ", "not-a-sha", "repo@zzz", 17, []):
            self.assertEqual(ev.parse_citation(value), ("", "", False))


class ScopeTests(unittest.TestCase):
    def test_generic_tokens_do_not_launder_an_integration_commit(self):
        scope = ev.declared_scope({"slug": "fix-src-test-index"})
        self.assertNotIn("src", scope)
        self.assertNotIn("test", scope)
        self.assertNotIn("index", scope)

    def test_overlap_finds_the_files_the_task_named(self):
        task = {"slug": "harden-merge-train-regression-gate"}
        hits = ev.scope_overlap(["runner/merge_train.py", "runner/verify.py"],
                                ev.declared_scope(task))
        self.assertEqual(hits, ("runner/merge_train.py",))

    def test_no_overlap_when_task_names_something_else(self):
        task = {"slug": "add-treasury-ledger-endpoint"}
        self.assertEqual(
            ev.scope_overlap(["runner/merge_train.py"], ev.declared_scope(task)), ())


class ClassifyTests(unittest.TestCase):
    def _task(self, slug, sha=TWO_FILE, repo="beethoven"):
        return {"id": "t-" + slug, "slug": slug,
                "artifact_commit": ev.format_citation(repo, sha) if repo else sha}

    def test_sole_claimant_of_a_resolvable_commit(self):
        v = ev.classify_claim(self._task("only-me"), "/repo", claim_count=1, runner=GIT)
        self.assertEqual(v["verdict"], ev.SOLE_CLAIMANT)

    def test_shared_commit_with_scope_overlap_is_justified(self):
        v = ev.classify_claim(self._task("harden-merge-train-gate"), "/repo",
                              claim_count=32, runner=GIT)
        self.assertEqual(v["verdict"], ev.JUSTIFIED)
        self.assertEqual(v["matched_files"], ("runner/merge_train.py",))

    def test_shared_commit_without_overlap_is_unattributed(self):
        """The 47f26779 shape: 32 claimants, 2 files, most cannot be justified."""
        v = ev.classify_claim(self._task("add-treasury-ledger-endpoint"), "/repo",
                              claim_count=32, runner=GIT)
        self.assertEqual(v["verdict"], ev.UNATTRIBUTED)
        self.assertIn("integration_commit", v["detail"])

    def test_absent_sha_is_unresolvable_not_an_exception(self):
        v = ev.classify_claim(self._task("x", sha="deadbeefdeadbeef"), "/repo",
                              claim_count=3, runner=GIT)
        self.assertEqual(v["verdict"], ev.UNRESOLVABLE)

    def test_no_citation(self):
        v = ev.classify_claim({"slug": "x", "artifact_commit": None}, "/repo", runner=GIT)
        self.assertEqual(v["verdict"], ev.NO_CITATION)

    def test_bad_input_does_not_raise(self):
        for task in (None, {}, "string", 5):
            v = ev.classify_claim(task, "/repo", runner=GIT)
            self.assertIn(v["verdict"], (ev.NO_CITATION, ev.UNRESOLVABLE))


class MergedGateTests(unittest.TestCase):
    def setUp(self):
        self.good = ev.classify_claim(
            {"id": "1", "slug": "harden-merge-train-gate",
             "artifact_commit": ev.format_citation("beethoven", TWO_FILE)},
            "/repo", claim_count=32, runner=GIT)
        self.bad = ev.classify_claim(
            {"id": "2", "slug": "add-treasury-ledger-endpoint",
             "artifact_commit": ev.format_citation("beethoven", TWO_FILE)},
            "/repo", claim_count=32, runner=GIT)

    def test_executor_may_never_set_merged(self):
        for role in ("executor", "cowork-executor-v6", "coder", "merge_train", "agent"):
            ok, why = ev.may_set_merged(role, self.good)
            self.assertFalse(ok, role)
            self.assertIn("executor", why)

    def test_verifier_may_set_merged_on_a_justified_verdict(self):
        ok, _ = ev.may_set_merged("verifier", self.good)
        self.assertTrue(ok)

    def test_verifier_may_not_set_merged_on_an_unattributed_verdict(self):
        ok, why = ev.may_set_merged("verifier", self.bad)
        self.assertFalse(ok)
        self.assertIn(ev.UNATTRIBUTED, why)

    def test_unknown_role_and_missing_verdict_fail_closed(self):
        self.assertFalse(ev.may_set_merged("", self.good)[0])
        self.assertFalse(ev.may_set_merged("mystery", self.good)[0])
        self.assertFalse(ev.may_set_merged("verifier", None)[0])


class AuditRowTests(unittest.TestCase):
    def test_row_carries_repo_sha_verdict_and_actor(self):
        v = ev.classify_claim(
            {"id": "9", "slug": "harden-merge-train-gate",
             "artifact_commit": ev.format_citation("beethoven", TWO_FILE)},
            "/repo", claim_count=32, runner=GIT)
        row = ev.audit_row(v, "verifier", "p1_backfill_classify",
                           previous_state="MERGED", new_state="MERGED")
        self.assertEqual(row["repo"], "beethoven")
        self.assertEqual(row["sha"], TWO_FILE)
        self.assertEqual(row["verdict"], ev.JUSTIFIED)
        self.assertEqual(row["claim_count"], 32)
        self.assertEqual(row["actor_role"], "verifier")
        self.assertTrue(row["repo_known"])

    def test_row_from_garbage_is_still_a_row(self):
        row = ev.audit_row(None, None, "noop")
        self.assertEqual(row["verdict"], ev.UNRESOLVABLE)


if __name__ == "__main__":
    unittest.main()
