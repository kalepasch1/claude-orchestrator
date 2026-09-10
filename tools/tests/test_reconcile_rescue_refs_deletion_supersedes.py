"""Unit tests for the newer-lineage deletion check in the rescue-ref reconciler.

Run: python3 -m unittest discover -s tools -p 'test_*.py'

REGRESSION UNDER TEST. `reconcile_rescue_refs.py` asks "does this diff still apply
to --base?" and calls a clean answer RECOVERABLE_VALUE. The base is usually behind:
the merge train holds unpushed commits for hours. So a ref can apply cleanly for the
worst possible reason — the base still contains the very files a newer commit
deleted on purpose, and "recovering" it undoes that deletion.

Reconciling beethoven under fingerprint 169a0a07fa18, that was 59 of 151
RECOVERABLE_VALUE verdicts. All 59 touched only web/types/log.js and
web/utils/cookie-compat.js, removed by d63e93da1 the day before the scan:
"finish fbd49cff8: drop the last 2 compiled .js files shadowing their .ts sources".
d63e93da1 was on local master and orchestrator/dev, not yet on origin/master.
Applying them would have re-added compiled .js files shadowing their TypeScript
sources — reintroducing the bug fbd49cff8 was written to fix.

The rule itself is pure and tested with injected predicates. The two predicates that
touch git are tested against real repositories, following this suite's convention:
a mock would happily agree with a wrong git command.
"""

import os
import subprocess
import tempfile
import unittest

import reconcile_rescue_refs as r


def run(repo, *args):
    subprocess.run(["git", "-C", repo, *args], check=True,
                   capture_output=True, text=True)


def write(repo, rel, body):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path) or repo, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(body)


def commit(repo, message):
    run(repo, "add", "-A")
    run(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", message)


def make_repo():
    repo = tempfile.mkdtemp()
    run(repo, "init", "-q", "-b", "base")
    return repo


class TestDeletionSupersedesRule(unittest.TestCase):
    """The pure rule: every touched path in the base, none of them on the newer tip."""

    @staticmethod
    def rule(files, in_base, in_newest):
        return r.deletion_supersedes(
            files, lambda f: f in in_base, lambda f: f in in_newest
        )

    def test_the_case_this_was_written_for(self):
        files = ["web/types/log.js", "web/utils/cookie-compat.js"]
        self.assertTrue(self.rule(files, in_base=set(files), in_newest=set()))

    def test_a_file_the_newer_lineage_still_has_is_not_superseded(self):
        # The ordinary case. Nothing was deleted, so the ref may still hold value
        # and must fall through to the apply check.
        self.assertFalse(self.rule(["a.py"], in_base={"a.py"}, in_newest={"a.py"}))

    def test_one_surviving_file_is_enough_to_keep_the_whole_ref(self):
        # ALL, not ANY, and deliberately. A ref that adds a deleted file AND a live
        # one still carries the live one; classifying it superseded would drop real
        # work to avoid resurrecting junk. Partial recovery is a focused follow-up,
        # not something this rule may decide on its own.
        self.assertFalse(self.rule(
            ["web/types/log.js", "runner/db.py"],
            in_base={"web/types/log.js", "runner/db.py"},
            in_newest={"runner/db.py"},
        ))

    def test_a_file_absent_from_both_is_not_a_deletion(self):
        # Absent from the base too means the base never had it — that is a genuine
        # recovery candidate, not something the newer lineage removed. Treating it
        # as superseded would discard exactly the work this tool exists to find.
        self.assertFalse(self.rule(["new.py"], in_base=set(), in_newest=set()))

    def test_no_files_is_never_superseded(self):
        # An empty sweep commit is handled earlier as ALREADY_PRESENT. all([]) is
        # True, so without the guard this would swallow it under the wrong label.
        for empty in ([], None, ()):
            self.assertFalse(self.rule(empty, in_base=set(), in_newest=set()))

    def test_the_predicates_are_the_only_thing_touching_the_repo(self):
        # If the rule ever grows a git call of its own it stops being testable
        # this way. Calling it with predicates that raise proves it does not.
        def boom(_f):
            raise AssertionError("the rule must not look past its predicates")

        self.assertFalse(r.deletion_supersedes([], boom, boom))


class TestGitPredicates(unittest.TestCase):
    """Real repositories: the predicates' whole job is reading git correctly."""

    def setUp(self):
        r.path_in_tree.cache_clear()
        r.deleting_commit.cache_clear()
        self.repo = make_repo()
        self.cwd = os.getcwd()
        write(self.repo, "web/types/log.js", "// compiled\n")
        write(self.repo, "web/types/log.ts", "export const x = 1\n")
        write(self.repo, "runner/db.py", "x = 1\n")
        commit(self.repo, "base state")
        run(self.repo, "branch", "newer")
        run(self.repo, "checkout", "-q", "newer")
        run(self.repo, "rm", "-q", "web/types/log.js")
        commit(self.repo, "drop the compiled .js shadowing its .ts source")
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.cwd)
        r.path_in_tree.cache_clear()
        r.deleting_commit.cache_clear()

    def test_path_in_tree_reads_each_ref_separately(self):
        self.assertTrue(r.path_in_tree("base", "web/types/log.js"))
        self.assertFalse(r.path_in_tree("newer", "web/types/log.js"))
        self.assertTrue(r.path_in_tree("newer", "web/types/log.ts"))

    def test_path_in_tree_matches_whole_path_components_only(self):
        # A partial filename matches nothing — a sloppier implementation grepping
        # the tree listing would match both log.js and log.ts here.
        self.assertFalse(r.path_in_tree("base", "web/types/lo"))
        self.assertFalse(r.path_in_tree("base", "web/types/log"))
        # A DIRECTORY does match, because that is what a git pathspec means. Callers
        # only ever pass file paths out of changed_files(), so this never fires in
        # practice; pinned so nobody "fixes" it into an exact-path check and
        # quietly changes what a pathspec means everywhere else in this module.
        self.assertTrue(r.path_in_tree("base", "web"))

    def test_an_unknown_ref_answers_false_rather_than_raising(self):
        # A caller passing --newest for a branch that does not exist locally must
        # get a quiet no, not a crash that leaves 771 refs unclassified.
        self.assertFalse(r.path_in_tree("no-such-ref", "runner/db.py"))
        self.assertEqual(r.deleting_commit("no-such-ref", "runner/db.py"), "")

    def test_deleting_commit_names_the_commit_that_removed_the_file(self):
        who = r.deleting_commit("newer", "web/types/log.js")
        self.assertIn("drop the compiled .js shadowing its .ts source", who)
        # Nothing deleted runner/db.py, so there is nothing to name.
        self.assertEqual(r.deleting_commit("newer", "runner/db.py"), "")

    def test_the_rule_over_real_git_state(self):
        superseded = r.deletion_supersedes(
            ["web/types/log.js"],
            lambda f: r.path_in_tree("base", f),
            lambda f: r.path_in_tree("newer", f),
        )
        self.assertTrue(superseded)

        survives = r.deletion_supersedes(
            ["web/types/log.js", "runner/db.py"],
            lambda f: r.path_in_tree("base", f),
            lambda f: r.path_in_tree("newer", f),
        )
        self.assertFalse(survives)


class TestClassifyWiring(unittest.TestCase):
    """The check is opt-in, and when it fires the ledger says why."""

    def setUp(self):
        r.path_in_tree.cache_clear()
        r.deleting_commit.cache_clear()
        self.repo = make_repo()
        write(self.repo, "web/types/log.js", "// compiled\n")
        write(self.repo, "runner/db.py", "x = 1\n")
        commit(self.repo, "base state")
        run(self.repo, "branch", "newer")
        run(self.repo, "checkout", "-q", "newer")
        run(self.repo, "rm", "-q", "web/types/log.js")
        commit(self.repo, "drop the compiled .js shadowing its .ts source")
        run(self.repo, "checkout", "-q", "base")
        # A rescue ref that re-adds the deleted file, off the base.
        run(self.repo, "checkout", "-q", "-b", "rescue")
        write(self.repo, "web/types/log.js", "// compiled, again\n")
        commit(self.repo, "orch-rescue: periodic sweep")
        self.sha = subprocess.run(
            ["git", "-C", self.repo, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip()
        run(self.repo, "checkout", "-q", "base")
        self.cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.cwd)
        r.path_in_tree.cache_clear()
        r.deleting_commit.cache_clear()

    # Far enough in the future that step 5 ("base has touched every path SINCE the
    # ref was cut") cannot fire. Step 5 and step 5b both answer SUPERSEDED_BY_NEWER,
    # so a ref that trips step 5 would make these tests pass for the wrong reason —
    # which is what happened on the first run of this file.
    AFTER_EVERYTHING = 4102444800  # 2100-01-01

    def _classify(self, newest):
        it = r.Item(ref="refs/orch-rescue/x", sha=self.sha,
                    subject="orch-rescue: periodic sweep",
                    created_at=self.AFTER_EVERYTHING)
        r.classify(it, "base", set(), newest)
        return it

    def test_without_newest_the_ref_still_reads_as_recoverable(self):
        # Default behaviour is unchanged, which is the point: a caller that does
        # not pass --newest gets exactly the classification it got before.
        self.assertEqual(self._classify("").classification, "RECOVERABLE_VALUE")

    def test_with_newest_the_same_ref_is_superseded(self):
        it = self._classify("newer")
        self.assertEqual(it.classification, "SUPERSEDED_BY_NEWER")

    def test_the_record_says_what_would_have_gone_wrong(self):
        # The ledger is read by people deciding whether to act, so a refusal has to
        # explain itself and name the commit, not just carry a label.
        it = self._classify("newer")
        self.assertIn("recovering would undo that deletion", it.disposition)
        self.assertIn("shadowing", it.evidence)
        self.assertIn("newer", it.evidence)


if __name__ == "__main__":
    unittest.main()
