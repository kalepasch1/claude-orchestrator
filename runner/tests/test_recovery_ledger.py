"""A validator that only ever passes proves nothing.

Every test here feeds recovery_ledger.validate() a ledger that is wrong in exactly one
way and asserts it says so. The three conditions under test are the completion contract
of a reconciliation pass: zero UNKNOWN items, one record per manifest item, and reachable
branch/commit provenance for anything still claimed to hold value.

Git-backed tests use a REAL repository rather than mocks, because "is this commit
reachable" is a question about git's object store and a mock would answer whatever the
test asserted.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import recovery_ledger


def _write(path, obj):
    with open(path, "w") as fh:
        json.dump(obj, fh)


class LedgerValidationTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.ledger = os.path.join(self.tmp, "recovery-ledger-test.json")
        self.manifest = os.path.join(self.tmp, "evidence_manifest-test.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _validate(self, records, items=None, repo="."):
        _write(self.ledger, {"audit_fingerprint": "t", "items": records})
        if items is None:
            items = [{"source": r.get("source", "")} for r in records]
        _write(self.manifest, {"items": items})
        return recovery_ledger.validate(self.ledger, repo, self.manifest)

    # ── condition 1: zero UNKNOWN ────────────────────────────────────────────

    def test_a_clean_ledger_is_valid_and_summarises_by_classification(self):
        result = self._validate([
            {"source": "agent/a", "classification": "ALREADY_PRESENT", "disposition": "in base"},
            {"source": "agent/b", "classification": "SUPERSEDED_BY_NEWER", "disposition": "newer wins"},
        ])
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["summary"],
                         {"ALREADY_PRESENT": 1, "SUPERSEDED_BY_NEWER": 1})

    def test_an_unknown_classification_fails(self):
        result = self._validate([
            {"source": "agent/a", "classification": "UNKNOWN", "disposition": "?"}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("UNKNOWN" in e for e in result["errors"]))

    def test_a_missing_classification_counts_as_unknown_and_fails(self):
        # The gap that lets an unfinished pass look finished: a record with no verdict.
        result = self._validate([{"source": "agent/a", "disposition": "looked at it"}])
        self.assertFalse(result["ok"])
        self.assertEqual(result["summary"].get("UNKNOWN"), 1)

    def test_a_classification_without_a_disposition_fails(self):
        # A verdict with no reason is not auditable, which is the point of the ledger.
        result = self._validate([{"source": "agent/a", "classification": "ALREADY_PRESENT"}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("no disposition" in e for e in result["errors"]))

    # ── condition 2: exactly one record per manifest item ────────────────────

    def test_a_manifest_item_with_no_record_fails(self):
        result = self._validate(
            [{"source": "agent/a", "classification": "ALREADY_PRESENT", "disposition": "in base"}],
            items=[{"source": "agent/a"}, {"source": "agent/unclassified"}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("agent/unclassified" in e for e in result["errors"]))

    def test_a_duplicate_record_fails(self):
        # 7.4x re-classification is the measured failure this check exists to catch.
        rec = {"source": "agent/a", "classification": "ALREADY_PRESENT", "disposition": "in base"}
        result = self._validate([rec, dict(rec)], items=[{"source": "agent/a"}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("expected exactly 1" in e for e in result["errors"]))

    def test_a_record_for_an_item_not_in_the_manifest_fails(self):
        result = self._validate(
            [{"source": "agent/ghost", "classification": "ALREADY_PRESENT", "disposition": "x"}],
            items=[])
        self.assertFalse(result["ok"])
        self.assertTrue(any("not in the manifest" in e for e in result["errors"]))

    def test_an_absent_manifest_fails_rather_than_silently_skipping_the_check(self):
        _write(self.ledger, {"items": [
            {"source": "agent/a", "classification": "ALREADY_PRESENT", "disposition": "x"}]})
        result = recovery_ledger.validate(self.ledger, ".", os.path.join(self.tmp, "nope.json"))
        self.assertFalse(result["ok"])
        self.assertTrue(any("no evidence manifest" in e for e in result["errors"]))

    # ── condition 3: RECOVERABLE_VALUE must be reachable ─────────────────────

    def test_recoverable_value_without_provenance_fails(self):
        result = self._validate([
            {"source": "agent/a", "classification": "RECOVERABLE_VALUE",
             "disposition": "still needed"}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("no branch" in e for e in result["errors"]))
        self.assertTrue(any("no commit" in e for e in result["errors"]))

    def test_a_fabricated_commit_sha_fails(self):
        # rev-parse would echo a well-formed hex string straight back; cat-file -e is what
        # makes an invented sha fail instead of validating.
        result = self._validate([
            {"source": "agent/a", "classification": "RECOVERABLE_VALUE",
             "disposition": "still needed", "branch": "agent/a",
             "commit": "0" * 40}])
        self.assertFalse(result["ok"])
        self.assertTrue(any("not reachable" in e for e in result["errors"]))

    def test_only_recoverable_value_needs_provenance(self):
        # The other four dispositions assert nothing is owed, so demanding a destination
        # for them would make every honest ledger invalid.
        result = self._validate([
            {"source": "agent/a", "classification": "ALREADY_PRESENT", "disposition": "in base"},
            {"source": "agent/b", "classification": "ACTIVE_IN_ANOTHER_TASK", "disposition": "held"},
            {"source": "agent/c", "classification": "CONFLICTED_NEEDS_FOCUSED_TASK",
             "disposition": "queued follow-up"}])
        self.assertTrue(result["ok"], result["errors"])

    def test_an_unreadable_ledger_reports_rather_than_raises(self):
        with open(self.ledger, "w") as fh:
            fh.write("{not json")
        result = recovery_ledger.validate(self.ledger, ".", self.manifest)
        self.assertFalse(result["ok"])
        self.assertIn("unreadable", result["errors"][0])


class GitBackedProvenanceTest(unittest.TestCase):
    """Reachability, against a real repo with a real bare origin."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.origin = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "work")
        subprocess.run(["git", "init", "--bare", "-q", self.origin], check=True, timeout=30)
        subprocess.run(["git", "clone", "-q", self.origin, self.repo], check=True, timeout=30)
        for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
            subprocess.run(["git", "config", k, v], cwd=self.repo, check=True, timeout=30)
        open(os.path.join(self.repo, "f.txt"), "w").write("base\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "push", "-q", "origin", "HEAD:master"], cwd=self.repo,
                       check=True, timeout=30)
        self.base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                                       capture_output=True, text=True, timeout=30).stdout.strip()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _branch(self, slug, content):
        subprocess.run(["git", "checkout", "-q", "master"], cwd=self.repo, timeout=30)
        subprocess.run(["git", "checkout", "-qb", f"agent/{slug}"], cwd=self.repo,
                       check=True, timeout=30)
        open(os.path.join(self.repo, f"{slug}.txt"), "w").write(content)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "commit", "-qm", f"agent: {slug}"], cwd=self.repo,
                       check=True, timeout=30)
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                              capture_output=True, text=True, timeout=30).stdout.strip()

    def test_a_real_commit_is_reachable_and_an_invented_one_is_not(self):
        self.assertTrue(recovery_ledger.commit_reachable(self.repo, self.base_sha))
        self.assertFalse(recovery_ledger.commit_reachable(self.repo, "0" * 40))
        self.assertFalse(recovery_ledger.commit_reachable(self.repo, ""))
        self.assertFalse(recovery_ledger.commit_reachable(self.repo, None))

    def test_branch_exists_accepts_a_local_only_branch(self):
        self._branch("local-only", "x")
        self.assertTrue(recovery_ledger.branch_exists(self.repo, "agent/local-only"))
        self.assertFalse(recovery_ledger.branch_exists(self.repo, "agent/never-existed"))

    def test_a_branch_contained_in_the_base_is_already_present(self):
        sha = self._branch("landed", "x")
        subprocess.run(["git", "checkout", "-q", "master"], cwd=self.repo, timeout=30)
        subprocess.run(["git", "merge", "-q", "--ff-only", "agent/landed"], cwd=self.repo,
                       check=True, timeout=30)
        cls, _disp = recovery_ledger.classify_branch(self.repo, "agent/landed", sha, "master")
        self.assertEqual(cls, "ALREADY_PRESENT")

    def test_a_live_task_outranks_recovery(self):
        # Recovering a branch someone still owns forks one change into two. The live-task
        # check must therefore win over "has a diff", not the other way round.
        sha = self._branch("held", "x")
        cls, _ = recovery_ledger.classify_branch(self.repo, "agent/held", sha, "master",
                                                 live_slugs={"held"})
        self.assertEqual(cls, "ACTIVE_IN_ANOTHER_TASK")
        cls, _ = recovery_ledger.classify_branch(self.repo, "agent/held", sha, "master",
                                                 live_slugs=set())
        self.assertEqual(cls, "RECOVERABLE_VALUE")

    def test_an_unreachable_commit_is_conflicted_not_recoverable(self):
        # "I cannot see it" must not read as "it is lost and I can rebuild it": a pruned
        # object here may be intact on another host.
        cls, _ = recovery_ledger.classify_branch(self.repo, "agent/gone", "0" * 40, "master")
        self.assertEqual(cls, "CONFLICTED_NEEDS_FOCUSED_TASK")

    def test_a_built_ledger_validates_against_its_own_manifest(self):
        # End to end: build then validate, which is the acceptance test the task states.
        self._branch("one", "x")
        self._branch("two", "y")
        manifest, ledger = recovery_ledger.build(self.repo, "fp", "master", live_slugs=set(),
                                                 ledger_dir="does-not-exist")
        mpath = os.path.join(self.tmp, "evidence_manifest-fp.json")
        lpath = os.path.join(self.tmp, "recovery-ledger-fp.json")
        _write(mpath, manifest)
        _write(lpath, ledger)
        result = recovery_ledger.validate(lpath, self.repo, mpath)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(sum(result["summary"].values()), len(manifest["items"]))
        self.assertEqual(ledger["unknown"], 0)


class RescueRefEvidenceTest(unittest.TestCase):
    """Rescue refs live at refs/orch-rescue/<name>, not refs/heads or refs/remotes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "work")
        subprocess.run(["git", "init", "-q", self.repo], check=True, timeout=30)
        for k, v in (("user.name", "t"), ("user.email", "t@t"), ("commit.gpgsign", "false")):
            subprocess.run(["git", "config", k, v], cwd=self.repo, check=True, timeout=30)
        open(os.path.join(self.repo, "f.txt"), "w").write("base\n")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "commit", "-qm", "base"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "branch", "-M", "master"], cwd=self.repo, check=True, timeout=30)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _rescue(self, name, content):
        subprocess.run(["git", "checkout", "-q", "-b", "tmpwork", "master"],
                       cwd=self.repo, timeout=30)
        open(os.path.join(self.repo, f"{name}.txt"), "w").write(content)
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "commit", "-qm", f"rescue {name}"], cwd=self.repo,
                       check=True, timeout=30)
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo,
                             capture_output=True, text=True, timeout=30).stdout.strip()
        subprocess.run(["git", "update-ref", f"refs/orch-rescue/{name}", sha],
                       cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "checkout", "-q", "master"], cwd=self.repo, timeout=30)
        subprocess.run(["git", "branch", "-qD", "tmpwork"], cwd=self.repo, timeout=30)
        return sha

    def test_a_rescue_ref_is_reachable_even_though_it_is_not_a_branch(self):
        # The bug this pins: a heads/remotes-only probe reported EVERY rescue ref as
        # unreachable, which fails provenance on records whose objects are right there.
        # A false "not reachable" is the dangerous direction — it discards recoverable work.
        self._rescue("20260803T000716-example", "x")
        self.assertTrue(recovery_ledger.branch_exists(self.repo,
                                                      "orch-rescue/20260803T000716-example"))
        self.assertFalse(recovery_ledger.branch_exists(self.repo, "orch-rescue/never-swept"))

    def test_rescue_refs_are_enumerated_and_agent_branches_are_not(self):
        self._rescue("sweep-a", "a")
        self._rescue("sweep-b", "b")
        subprocess.run(["git", "checkout", "-qb", "agent/unrelated"], cwd=self.repo, timeout=30)
        manifest, ledger = recovery_ledger.build(
            self.repo, "fp", "master", live_slugs=set(), ledger_dir="none",
            evidence_kind="orchestrator_rescue_ref")
        sources = {i["source"] for i in manifest["items"]}
        self.assertEqual(sources, {"orch-rescue/sweep-a", "orch-rescue/sweep-b"})
        self.assertEqual(ledger["evidence_kind"], "orchestrator_rescue_ref")
        self.assertTrue(all(r["kind"] == "orchestrator_rescue_ref" for r in ledger["items"]))

    def test_two_sweeps_of_one_branch_stay_two_records(self):
        # Rescue refs must NOT be name-normalised the way agent branches are: each is a
        # distinct timestamped snapshot of a checkout, so two sweeps are two different
        # trees. Collapsing them would silently drop one of the items the contract
        # ("one record per evidence item") requires to be classified.
        self._rescue("20260803T000716-merged-diff-memory", "first")
        self._rescue("20260803T000751-merged-diff-memory", "second")
        manifest, _ledger = recovery_ledger.build(
            self.repo, "fp", "master", live_slugs=set(), ledger_dir="none",
            evidence_kind="orchestrator_rescue_ref")
        self.assertEqual(len(manifest["items"]), 2)

    def test_a_recoverable_rescue_ref_is_routed_to_a_new_branch_not_the_ref_itself(self):
        # The evidence source is read-only by contract, so the disposition must not tell a
        # reader to deliver "via the agent branch" — there is no agent branch here.
        sha = self._rescue("sweep-c", "c")
        cls, disp = recovery_ledger.classify_branch(
            self.repo, "orch-rescue/sweep-c", sha, "master")
        self.assertEqual(cls, "RECOVERABLE_VALUE")
        self.assertIn("read-only", disp)

    def test_a_built_rescue_ledger_validates(self):
        self._rescue("sweep-d", "d")
        manifest, ledger = recovery_ledger.build(
            self.repo, "fp", "master", live_slugs=set(), ledger_dir="none",
            evidence_kind="orchestrator_rescue_ref")
        mpath = os.path.join(self.tmp, "evidence_manifest-fp.json")
        lpath = os.path.join(self.tmp, "recovery-ledger-fp.json")
        _write(mpath, manifest)
        _write(lpath, ledger)
        result = recovery_ledger.validate(lpath, self.repo, mpath)
        self.assertTrue(result["ok"], result["errors"])

    def test_agent_branch_enumeration_is_unchanged_by_the_new_kind(self):
        # The sibling task's ledger must keep validating; adding a kind must not move the
        # default behaviour.
        self._rescue("sweep-e", "e")
        subprocess.run(["git", "checkout", "-qb", "agent/real-work"], cwd=self.repo, timeout=30)
        open(os.path.join(self.repo, "w.txt"), "w").write("w")
        subprocess.run(["git", "add", "-A"], cwd=self.repo, check=True, timeout=30)
        subprocess.run(["git", "commit", "-qm", "agent: real-work"], cwd=self.repo,
                       check=True, timeout=30)
        manifest, _l = recovery_ledger.build(self.repo, "fp", "master", live_slugs=set(),
                                             ledger_dir="none")
        sources = {i["source"] for i in manifest["items"]}
        self.assertEqual(sources, {"agent/real-work"})


class KnownDispositionsTest(unittest.TestCase):
    """The anti-duplication primitive: read what predecessors already decided."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".orch"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _ledger(self, name, obj):
        _write(os.path.join(self.tmp, ".orch", name), obj)

    def test_it_reads_every_historical_ledger_shape(self):
        # The 19 committed ledgers use at least three shapes. A reader that understood
        # only the newest would re-derive everything the older passes already knew, which
        # is precisely how 1,279 distinct sources became 9,481 rows.
        self._ledger("recovery-ledger-a.json",
                     {"items": [{"ref": "agent/a", "classification": "ALREADY_PRESENT"}]})
        self._ledger("recovery-ledger-b.json",
                     {"evidence_items": [{"source": "agent/b",
                                          "classification": "SUPERSEDED_BY_NEWER"}]})
        self._ledger("recovery-ledger-c.json",
                     [{"branch": "agent/c", "classification": "RECOVERABLE_VALUE"}])
        known = recovery_ledger.known_dispositions(self.tmp)
        self.assertEqual(known["agent/a"], "ALREADY_PRESENT")
        self.assertEqual(known["agent/b"], "SUPERSEDED_BY_NEWER")
        self.assertEqual(known["agent/c"], "RECOVERABLE_VALUE")

    def test_a_corrupt_ledger_is_reported_not_silently_treated_as_empty(self):
        with open(os.path.join(self.tmp, ".orch", "recovery-ledger-bad.json"), "w") as fh:
            fh.write("{oops")
        loaded = recovery_ledger.load_ledgers(self.tmp)
        self.assertEqual([obj for _p, obj in loaded], [None])

    def test_no_ledger_directory_answers_empty_rather_than_raising(self):
        self.assertEqual(recovery_ledger.known_dispositions("/nonexistent/path"), {})


if __name__ == "__main__":
    unittest.main()
