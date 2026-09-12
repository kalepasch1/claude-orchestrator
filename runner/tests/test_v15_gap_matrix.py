"""Machine-checked V15 fleet gap matrix (docs/v15-00-baseline-contract-audit-slice-2.md).

An audit written only as prose ages into fiction: the adoption states stay on the page
long after they stop being true. These tests pin the matrix to facts that can be
re-derived — the app-id list it is indexed by, the claims it makes about THIS repository,
and, where a sibling repo is present on the machine, the evidence file each row cites.

Rows for repositories that are not checked out are skipped rather than assumed. "Not
assessed" is the honest state for a repo nobody can see, and asserting `none` for it would
be inventing a fact.
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hivemind_v15

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DOC = os.path.join(_REPO, "docs", "v15-00-baseline-contract-audit-slice-2.md")
_SLICE1 = os.path.join(_REPO, "docs", "v15-00-baseline-contract-audit-slice-1.md")
_TS = os.path.join(_REPO, "packages", "darwin-kernel", "src", "hivemindV15", "index.ts")

#: Sibling checkouts, and the file each matrix row cites as its evidence.
_SIBLINGS = {
    # galop's evidence is an ABSENCE, and the None marks it as such. The adapter
    # lib/v15Adapter.ts was written and never landed: it exists in a `WIP on master`
    # stash and under racefeed-wt/, on no branch of racefeed. The row is `none`, the
    # doc says why, and test_galop_has_no_landed_seam asserts the absence directly —
    # so this table must not also demand the file exist.
    "galop": ("/Users/kpasch/Documents/galop/racefeed", None, "none"),
    "hisanta": ("/Users/kpasch/Documents/hisanta", "DARWIN_KERNEL_ADOPTION.md", "planned"),
    "trojun": ("/Users/kpasch/Documents/trojun", "types/index.ts", "none"),
}


def _doc():
    with open(_DOC, encoding="utf-8") as fh:
        return fh.read()


class MatrixShapeTest(unittest.TestCase):
    def test_the_audit_document_exists(self):
        self.assertTrue(os.path.isfile(_DOC))

    def test_it_continues_slice_one_rather_than_replacing_it(self):
        self.assertTrue(os.path.isfile(_SLICE1), "slice 1 must still be the inventory")
        self.assertIn("v15-00-baseline-contract-audit-slice-1.md", _doc())

    def test_every_app_id_has_a_matrix_row(self):
        """The matrix is indexed by HIVEMIND_APPS; a new app must not silently escape it."""
        doc = _doc()
        for app in hivemind_v15.FLEET_APPS:
            self.assertIn(f"`{app}`", doc, f"{app} has no row in the gap matrix")

    def test_it_cites_the_audited_commits(self):
        doc = _doc()
        self.assertIn("b3d38813", doc)
        self.assertIn("e2834ef5", doc)

    def test_only_the_defined_adoption_states_are_used(self):
        """A row must use a state the document defines, not an ad-hoc word."""
        states = set(re.findall(r"\*\*(native|seam|planned|none|absent)\*\*", _doc()))
        self.assertTrue(states, "no adoption states found")
        self.assertLessEqual(states, {"native", "seam", "planned", "none", "absent"})


class ClaimsAboutThisRepoTest(unittest.TestCase):
    """The `orchestrator` row is the one this repository can fully verify."""

    def test_the_runtime_files_the_audit_names_exist(self):
        self.assertTrue(os.path.isfile(_TS))
        self.assertTrue(os.path.isfile(os.path.join(_REPO, "runner", "hivemind_v15.py")))

    def test_the_kernel_still_re_exports_the_runtime(self):
        with open(os.path.join(_REPO, "packages", "darwin-kernel", "src", "index.ts"),
                  encoding="utf-8") as fh:
            self.assertIn("hivemindV15", fh.read())

    def test_the_orchestrator_really_is_a_native_consumer(self):
        with open(os.path.join(_REPO, "runner", "runner.py"), encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("hivemind_v15", src, "the native row claims an intake hook here")

    def test_the_runtime_still_holds_no_persistent_state(self):
        """The blocking gap. If serialization lands, this document is out of date."""
        with open(_TS, encoding="utf-8") as fh:
            src = fh.read()
        for method in ("serialize", "toJSON", "restore", "hydrate"):
            self.assertNotIn(f"{method}(", src,
                             f"{method}() exists now — the blocking gap in slice 2 is stale")


class BenchmarkHonestyTest(unittest.TestCase):
    def test_no_speed_multiplier_is_claimed(self):
        """The brief forbids 50X-500X claims without a reproduced benchmark."""
        doc = _doc()
        self.assertIn("makes no performance claim", doc)
        for hit in re.findall(r"\b\d+[Xx]\b", doc):
            self.assertIn("hypothes", doc.lower(),
                          f"{hit} appears without the hypothesis framing")

    def test_the_runtime_header_agrees_that_figures_are_targets(self):
        with open(_TS, encoding="utf-8") as fh:
            self.assertIn("benchmark targets, not promises", fh.read())


class SiblingRepoEvidenceTest(unittest.TestCase):
    """Where a sibling checkout exists, its cited evidence file must exist too."""

    def test_cited_evidence_files_are_real(self):
        checked = 0
        for app, (root, evidence, state) in _SIBLINGS.items():
            if not os.path.isdir(root):
                continue                      # not checked out: no claim to verify
            if evidence is None:
                # The row's evidence IS the absence of a file — see the galop entry.
                # A dedicated test asserts that absence; demanding a path here would
                # require inventing one.
                continue
            checked += 1
            path = os.path.join(root, evidence)
            self.assertTrue(os.path.isfile(path),
                            f"{app} row cites {evidence}, which does not exist")
            self.assertIn(evidence, _doc())
        if not checked:
            self.skipTest("no sibling repositories present on this machine")

    def test_galop_has_no_landed_seam(self):
        """The row says `none`, and this is why.

        It used to assert that lib/v15Adapter.ts documents flags-off parity — the
        evidence for a `seam` row. Re-checked on 2026-09-05, that file is in no
        commit of racefeed: it exists in a `WIP on master` stash and under
        racefeed-wt/, and on no branch. The audit's own opening line warns that
        "an audit written only as prose ages into fiction"; this is that, caught
        by the test written to catch it.

        Asserting the absence keeps the claim machine-checked in the direction it
        is now true, so the row cannot quietly go back to claiming a seam without
        someone landing the adapter first.
        """
        root = _SIBLINGS["galop"][0]
        if not os.path.isdir(root):
            self.skipTest("galop/racefeed not present")
        self.assertFalse(
            os.path.isfile(os.path.join(root, "lib", "v15Adapter.ts")),
            "lib/v15Adapter.ts now EXISTS in racefeed — the adapter landed. Restore "
            "the galop row to **seam**, re-point _SIBLINGS at it, and assert parity "
            "again.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
