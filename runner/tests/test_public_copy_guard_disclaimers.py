#!/usr/bin/env python3
"""The public-copy guard must not order the deletion of a legal disclaimer.

copyfix-trojun-08171305 went RED four times on four findings, and all four were
false positives. The remediation instruction attached to them is "Remove/redact
ONLY the flagged content", so following it would have:

  * deleted `<p class="gc-disclaimer">Automated analysis. Not legal advice.</p>`
    and the EMPTY_VIEW disclaimer default - the notices whose entire purpose is to
    stop automated output being read as legal advice, i.e. it would have CREATED
    the exposure this guard exists to prevent; and
  * deleted two `$fetch('/api/cade/...')` calls, breaking the dossier feature, to
    "redact" a route already visible in any user's network tab.

Same class as the bug _block_comment_mask was added for, where the guard flagged a
comment documenting its own rule and stopped a release.

Both halves of the fix are narrow: "not legal advice" leaves the legal_strategy
alternation while the genuine posture claims stay in it, and route-shaped string
literals are masked before matching so a path cannot trip a prose term.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import public_copy_guard as guard


def _scan(path, line):
    return guard.scan_lines(path, [(1, line)])


class ADisclaimerIsNotAStrategyLeak(unittest.TestCase):

    def test_the_rendered_disclaimer_is_not_flagged(self):
        self.assertEqual(
            _scan("components/GradientCard.vue",
                  '<p class="gc-disclaimer">Automated analysis. Not legal advice.</p>'), [])

    def test_the_default_disclaimer_string_is_not_flagged(self):
        self.assertEqual(
            _scan("components/GradientDossier.vue",
                  "  disclaimer: 'Automated analysis dossier. Not legal advice.',"), [])

    def test_case_and_wording_variants_are_not_flagged(self):
        for line in ("<p>This is not legal advice.</p>",
                     "<p>NOT LEGAL ADVICE</p>",
                     "<span>Informational only — not legal advice</span>"):
            self.assertEqual(_scan("components/A.vue", line), [], line)


class RealPostureClaimsAreStillFlagged(unittest.TestCase):
    """The other members of that alternation ARE the playbook. Removing "legal
    advice" must not have loosened them."""

    def test_regulatory_posture_claims_still_flag(self):
        for line in ("<p>This is not money transmission under state law.</p>",
                     "<p>The service is not custody.</p>",
                     "<p>This is not securities.</p>",
                     "<p>We are not a broker-dealer.</p>"):
            self.assertTrue(_scan("components/A.vue", line), line)

    def test_strategy_language_still_flags(self):
        for line in ("<p>We use regulatory arbitrage to avoid CFTC registration.</p>",
                     "<p>Our privilege guard protects work-product strategy.</p>",
                     "<p>This avoids money transmission licensing.</p>"):
            self.assertTrue(_scan("components/A.vue", line), line)


class ARouteInCodeIsNotPublishedCopy(unittest.TestCase):

    def test_an_api_call_is_not_flagged(self):
        for line in ("const body = await $fetch('/api/cade/explain', {",
                     "const data = await $fetch(`/api/cade/gradient-job/${id}`)",
                     'const r = await $fetch("/api/cade/status")'):
            self.assertEqual(_scan("components/GradientDossier.vue", line), [], line)

    def test_import_and_alias_paths_are_not_flagged(self):
        for line in ("import { cade } from '~/utils/cade/common-brain'",
                     "const m = await import('@/components/cade/AgentMesh.vue')",
                     "const x = await import('./cade/hivemind')"):
            self.assertEqual(_scan("components/A.vue", line), [], line)

    def test_prose_naming_the_mechanism_still_flags(self):
        """The rule's actual target. Masking paths must not mask prose."""
        for line in ("<p>Our CADE engine routes every job.</p>",
                     "<p>Ask about our merged-diff library and patch transplant.</p>",
                     "<p>Read about CADE at /api/docs</p>"):
            self.assertTrue(_scan("components/A.vue", line), line)

    def test_a_bare_unquoted_route_in_prose_still_flags(self):
        """Only QUOTED route literals are masked; prose is untouched."""
        self.assertTrue(_scan("components/A.vue", "<p>See /api/cade/explain for details</p>"))


class TheFourReportedFindingsAreAllClean(unittest.TestCase):
    """End to end: the exact lines that failed this gate four times."""

    FINDINGS = [
        ("components/GradientCard.vue",
         '      <p class="gc-disclaimer">Automated analysis. Not legal advice.</p>'),
        ("components/GradientDossier.vue",
         "  disclaimer: 'Automated analysis dossier. Not legal advice.', askPrompt: '',"),
        ("components/GradientDossier.vue",
         "    const body = await $fetch('/api/cade/explain', {"),
        ("components/GradientDossier.vue",
         "    const data = await $fetch(`/api/cade/gradient-job/${encodeURIComponent(id)}`)"),
    ]

    def test_none_of_them_flag(self):
        for path, line in self.FINDINGS:
            self.assertEqual(_scan(path, line), [], f"{path}: {line.strip()}")


if __name__ == "__main__":
    unittest.main()
