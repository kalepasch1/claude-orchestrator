#!/usr/bin/env python3
"""The same request must produce the same patch-template id.

THE DEFECT. `_id()` hashed the WHOLE prompt, and the router staples an ORCHESTRATION
PIPELINE CONTRACT block onto every prompt whose cross-learning section is regenerated per
run — "recent outcome signal: 1/12 merged, models claude-fable-5", "learned route: ...".
So the identical request produced a different template id every time it was rebuilt.
Measured on master: ids 9fcaa09b35f9 and 11647833df90 for one request under two contexts.

WHY IT MATTERS. This module exists so a repair pass can REUSE prior work instead of
reconstructing it. An id that is a function of when it was computed means templates never
dedupe: every rebuild stores a new one, and a lookup of the prior id always misses. The
fleet then rebuilds work that already exists, which is its most expensive failure mode.

Proof: python3 -m pytest runner/tests/test_patch_template_id_stability.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_templates as pt  # noqa: E402

REQUEST = ("# Original improvement request\n"
           "Fix the scheduler so the queue drains oldest-first, and add a test "
           "covering queue starvation.")


def _contract(signal, models, route):
    return ("## ORCHESTRATION PIPELINE CONTRACT\n"
            "- source: preflight-gate\n"
            "- project: beethoven\n"
            "- cross-learning context:\n"
            f"  - recent outcome signal: {signal}\n"
            f"  - models {models}\n"
            f"  - learned route: {route}\n"
            "## END ORCHESTRATION PIPELINE CONTRACT\n")


CTX_A = _contract("1/12 merged, 1/12 test-pass", "claude-fable-5", "build_fix q=7.0")
CTX_B = _contract("7/12 merged, 4/12 test-pass", "deepseek grok-3-mini", "plan q=6.2")


class TestIdStability(unittest.TestCase):
    def _id(self, prompt, slug="fix-scheduler-starvation"):
        return pt._id({"slug": slug, "prompt": prompt})

    def test_the_same_request_under_different_fleet_context_has_one_id(self):
        """The reported defect, directly."""
        self.assertEqual(self._id(CTX_A + REQUEST), self._id(CTX_B + REQUEST))

    def test_a_bare_request_matches_the_same_request_with_a_contract(self):
        self.assertEqual(self._id(REQUEST), self._id(CTX_A + REQUEST))

    def test_a_genuinely_different_request_still_gets_a_different_id(self):
        other = "# Original improvement request\nRewrite the billing exporter in Rust."
        self.assertNotEqual(self._id(CTX_A + REQUEST), self._id(CTX_A + other))

    def test_the_slug_still_participates_in_the_id(self):
        self.assertNotEqual(self._id(REQUEST, slug="a"), self._id(REQUEST, slug="b"))

    def test_it_is_deterministic_across_calls(self):
        self.assertEqual(self._id(CTX_A + REQUEST), self._id(CTX_A + REQUEST))

    def test_reuse_preambles_do_not_move_the_id(self):
        noisy = ("MERGED-DIFF LIBRARY: adapt proven prior diffs before drafting.\n"
                 "SOURCE illuminati/some-slug similarity=0.405: PATCH TEMPLATE 182e72e\n"
                 "REUSE FIRST: a solved implementation exists.\n"
                 "SUMMARY: something\n" + REQUEST)
        self.assertEqual(self._id(REQUEST), self._id(noisy))


class TestRequestExtraction(unittest.TestCase):
    def test_the_contract_block_is_removed(self):
        text = pt._request_text({"prompt": CTX_A + REQUEST})
        self.assertNotIn("cross-learning", text)
        self.assertNotIn("claude-fable-5", text)

    def test_the_request_survives(self):
        text = pt._request_text({"prompt": CTX_A + REQUEST})
        self.assertIn("scheduler", text)
        self.assertIn("starvation", text)

    def test_a_prompt_with_no_contract_is_unchanged(self):
        self.assertEqual(pt._request_text({"prompt": REQUEST}), REQUEST)

    def test_a_prompt_that_is_only_a_contract_keeps_its_text(self):
        """Stripping to empty would collide every such task onto one id."""
        text = pt._request_text({"prompt": CTX_A})
        self.assertTrue(text.strip())

    def test_it_is_fail_soft(self):
        for bad in (None, "prompt", 7, [], {}, {"prompt": None}, {"prompt": 5}):
            self.assertIsInstance(pt._request_text(bad), str, bad)

    def test_case_insensitive_contract_markers_are_handled(self):
        lowered = CTX_A.replace("ORCHESTRATION PIPELINE CONTRACT",
                                "orchestration pipeline contract")
        self.assertNotIn("cross-learning",
                         pt._request_text({"prompt": lowered + REQUEST}))


class TestBuildStillWorks(unittest.TestCase):
    def test_build_returns_the_stable_id(self):
        task = {"slug": "s", "prompt": CTX_A + REQUEST}
        self.assertEqual(pt.build(task)[0], pt._id(task))

    def test_two_runs_of_the_same_request_build_the_same_id(self):
        a = pt.build({"slug": "s", "prompt": CTX_A + REQUEST})[0]
        b = pt.build({"slug": "s", "prompt": CTX_B + REQUEST})[0]
        self.assertEqual(a, b, "templates still fail to dedupe across runs")

    def test_the_body_still_has_its_sections(self):
        _, body = pt.build({"slug": "s", "prompt": CTX_A + REQUEST})
        for section in ("PATCH TEMPLATE", "Intent:", "Acceptance:", "Implementation slots:"):
            self.assertIn(section, body)

    def test_an_empty_prompt_does_not_raise(self):
        tid, body = pt.build({"slug": "s", "prompt": ""})
        self.assertTrue(tid)
        self.assertIn("PATCH TEMPLATE", body)

    def test_hints_are_still_extracted_from_the_request(self):
        intent = pt._intent({"slug": "s", "prompt": CTX_A + REQUEST})
        self.assertIn("test", intent["hints"])


if __name__ == "__main__":
    unittest.main()
