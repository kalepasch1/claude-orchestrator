"""A recovery-intent manifest is a stub wearing a filename instead of a function body.

390 of these are tracked across 8 live repos (pareto-2080 173, pasch 63, Sustainable_Barks 50,
racefeed 33, hisanta 33, pmi 19, apparently-law 18, smarter 1). Each is the task's own prompt
written back out as a file, with no code behind it. apparently-law's own suite states the rule
and is red on it: "a run with nothing real to ship must leave the task BLOCKED, not commit a
stub manifest".
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import stub_guard

MANIFEST = (
    "recovery-intent: backlog-batch-example-slice-4-do-the-thing\n"
    "template: 6c7ebe2aa79a\n"
    "intent: acceptance adapt analysis artifacts because before behavior below blocks\n"
    "originalbase: main\n"
)


def _git(repo, *args):
    return subprocess.run(["git"] + list(args), cwd=repo, capture_output=True,
                          text=True, timeout=30)


class IntentManifestStubTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="intentstub-")
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", self.dir], timeout=30))
        _git(self.dir, "init", "-q", "-b", "main")
        _git(self.dir, "config", "user.email", "t@example.com")
        _git(self.dir, "config", "user.name", "t")
        self._write("README.md", "hello\n")
        _git(self.dir, "add", "-A")
        _git(self.dir, "commit", "-qm", "base")
        self.base = _git(self.dir, "rev-parse", "HEAD").stdout.strip()
        _git(self.dir, "checkout", "-q", "-b", "cand")

    def _write(self, rel, text):
        p = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True) if os.path.dirname(rel) else None
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _commit(self, msg="cand"):
        _git(self.dir, "add", "-A")
        _git(self.dir, "commit", "-qm", msg)
        return _git(self.dir, "rev-parse", "HEAD").stdout.strip()

    def _scan(self):
        return stub_guard.scan_intent_stubs(self.dir, self.base, "HEAD")

    # ------------------------------------------------------------ the finding
    def test_a_newly_added_manifest_is_flagged(self):
        self._write(".recovery-intent-backlog-batch-example-slice-4.txt", MANIFEST)
        self._commit()
        found = self._scan()
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["code"], "intent_manifest_stub")

    def test_the_finding_blocks_rather_than_warns(self):
        self.assertIn("intent_manifest_stub", stub_guard.BLOCKING)
        self._write(".recovery-intent-x.txt", MANIFEST)
        self._commit()
        self.assertEqual(self._scan()[0]["severity"], "block")

    def test_several_manifests_are_reported_individually(self):
        for n in ("a", "b", "c"):
            self._write(".recovery-intent-%s.txt" % n, MANIFEST)
        self._commit()
        self.assertEqual(len(self._scan()), 3)

    def test_the_message_names_the_file_and_says_what_to_do(self):
        self._write(".recovery-intent-slice-9.txt", MANIFEST)
        self._commit()
        v = self._scan()[0]
        self.assertIn(".recovery-intent-slice-9.txt", v["detail"])
        self.assertIn("BLOCKED", v["detail"] + v["fix"])

    # -------------------------------------------------- what must NOT trigger
    def test_real_work_is_untouched(self):
        self._write("src/thing.ts", "export function add(a: number, b: number) { return a + b }\n")
        self._commit()
        self.assertEqual(self._scan(), [])

    def test_a_manifest_already_on_the_base_branch_never_blocks_a_candidate(self):
        """The 390 existing ones must not refuse every card in those projects forever."""
        _git(self.dir, "checkout", "-q", "main")
        self._write(".recovery-intent-preexisting.txt", MANIFEST)
        self._commit("pre-existing stub on base")
        self.base = _git(self.dir, "rev-parse", "HEAD").stdout.strip()
        _git(self.dir, "checkout", "-q", "cand")
        _git(self.dir, "merge", "-q", "--no-edit", "main")
        self._write("src/real.ts", "export const x = 1\n")
        self._commit()
        self.assertEqual(self._scan(), [])

    def test_deleting_a_manifest_is_never_penalised(self):
        """A candidate cleaning these up is doing the right thing."""
        _git(self.dir, "checkout", "-q", "main")
        self._write(".recovery-intent-old.txt", MANIFEST)
        self._commit("stub on base")
        self.base = _git(self.dir, "rev-parse", "HEAD").stdout.strip()
        _git(self.dir, "checkout", "-q", "cand")
        _git(self.dir, "merge", "-q", "--no-edit", "main")
        os.remove(os.path.join(self.dir, ".recovery-intent-old.txt"))
        self._commit("remove the stub")
        self.assertEqual(self._scan(), [])

    def test_a_matching_name_carrying_real_content_is_not_refused(self):
        """Confirmed by content as well as by name."""
        self._write(".recovery-intent-notes.txt",
                    "# Real notes about the recovery\n\nWe restored refs by hand; see PR 42.\n")
        self._commit()
        self.assertEqual(self._scan(), [])

    def test_an_ordinary_dotfile_is_not_a_manifest(self):
        self._write(".env.example", "API_KEY=\n")
        self._write("notes.txt", "recovery-intent: not at a manifest path\n")
        self._commit()
        self.assertEqual(self._scan(), [])

    def test_no_base_means_no_diff_and_so_no_finding(self):
        """The periodic whole-tree sweep is a different code path; this one needs a base."""
        self._write(".recovery-intent-x.txt", MANIFEST)
        self._commit()
        self.assertEqual(stub_guard.scan_intent_stubs(self.dir, None, "HEAD"), [])

    def test_a_repo_that_is_not_a_repo_returns_nothing_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(stub_guard.scan_intent_stubs(d, "main", "HEAD"), [])

    def test_check_repo_surfaces_it_and_turns_ok_false(self):
        self._write(".recovery-intent-gate.txt", MANIFEST)
        self._commit()
        res = stub_guard.check_repo(self.dir, branch="HEAD", project="t", base=self.base)
        codes = [v["code"] for v in res["violations"]]
        self.assertIn("intent_manifest_stub", codes)
        self.assertFalse(res["ok"])


if __name__ == "__main__":
    unittest.main()
