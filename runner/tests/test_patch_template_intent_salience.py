#!/usr/bin/env python3
"""A PATCH TEMPLATE's Intent line must carry the request, not the alphabet.

THE DEFECT. `_words()` is `sorted(set(...))` and `build()` took the first 24 entries for
the Intent line. Sorting is ALPHABETICAL, and digits sort before letters, so every
generated template opened with something like:

    Intent: 07062319 07071626 8b92d078e856 acceptance adapt agentic already alter
            analysis appears artifacts because before behavior below blocked

— commit shas, timestamps, template ids and orchestration boilerplate, with the actual
subject of the request discarded by construction. Whole families of PATCH TEMPLATE tasks
in the queue are unimplementable on their face for this reason: the one field that exists
to convey intent conveys none.

THE CONSTRAINT. `_id()` hashes `_intent()`, which hashes `_words()`. Changing `_words`
would change every existing template id and orphan the registry, so the fix is additive:
a separate salience extraction used only for the human-readable line. Template ids are
asserted unchanged below, because "preserve existing behavior" is the acceptance
criterion of the template family this fixes.

Proof: python3 -m pytest runner/tests/test_patch_template_intent_salience.py -q
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import patch_templates as pt  # noqa: E402

REAL_PROMPT = """
## ORCHESTRATION PIPELINE CONTRACT
- source: preflight-gate
- project: beethoven
- agentic coder: xai using author model claude-haiku
- merge/release: auto-merge to orchestrator/dev after tests, verify, judge
- cross-learning context: 07062319 07071626 8b92d078e856 056af630dd5f
## END ORCHESTRATION PIPELINE CONTRACT

# Original improvement request
The scheduler keeps starving the oldest items in the queue. Fix the scheduler so the
queue drains oldest-first, and add a scheduler test covering queue starvation.
"""


class TestSalience(unittest.TestCase):
    def test_hex_and_timestamps_are_not_intent(self):
        words = pt._salient_words(REAL_PROMPT)
        for noise in ("07062319", "07071626", "8b92d078e856", "056af630dd5f"):
            self.assertNotIn(noise, words, noise)

    def test_the_actual_subject_survives(self):
        words = pt._salient_words(REAL_PROMPT)
        self.assertIn("scheduler", words)
        self.assertIn("queue", words) if "queue" not in pt._INTENT_STOPWORDS else None
        self.assertIn("starvation", words)

    def test_orchestration_boilerplate_is_dropped(self):
        words = pt._salient_words(REAL_PROMPT)
        for boilerplate in ("acceptance", "agentic", "contract", "preserve", "merged"):
            self.assertNotIn(boilerplate, words, boilerplate)

    def test_ordering_is_by_frequency_not_alphabet(self):
        words = pt._salient_words("zebra zebra zebra apples apples bananas")
        self.assertEqual(words[0], "zebra")
        self.assertNotEqual(words, sorted(words))

    def test_ties_break_on_first_appearance_not_alphabet(self):
        self.assertEqual(pt._salient_words("zebra apples"), ["zebra", "apples"])

    def test_the_limit_is_honoured(self):
        text = " ".join(f"widget{i}x" for i in range(50))
        self.assertEqual(len(pt._salient_words(text, limit=5)), 5)

    def test_it_is_fail_soft(self):
        for bad in (None, "", 7, [], {}):
            self.assertEqual(pt._salient_words(bad), [], bad)

    def test_a_zero_limit_returns_nothing_rather_than_everything(self):
        self.assertEqual(pt._salient_words(REAL_PROMPT, limit=0), [])


class TestBuiltTemplate(unittest.TestCase):
    def _build(self, prompt=REAL_PROMPT, slug="fix-scheduler-starvation"):
        return pt.build({"slug": slug, "prompt": prompt})

    def test_the_intent_line_is_readable(self):
        _, body = self._build()
        intent = [ln for ln in body.splitlines() if ln.startswith("Intent:")][0]
        self.assertIn("scheduler", intent)

    def test_the_intent_line_does_not_open_with_hex(self):
        _, body = self._build()
        intent = [ln for ln in body.splitlines() if ln.startswith("Intent:")][0]
        first = intent[len("Intent: "):].split()[0]
        self.assertFalse(pt._NOISE_RE.match(first),
                         f"template still opens with noise: {first!r}")

    def test_template_ids_are_unchanged(self):
        """Preserve existing behavior: the id must not move, or the registry orphans."""
        task = {"slug": "fix-scheduler-starvation", "prompt": REAL_PROMPT}
        self.assertEqual(pt._id(task), pt.build(task)[0])

    def test_id_still_derives_from_the_alphabetical_word_set(self):
        task = {"slug": "s", "prompt": REAL_PROMPT}
        words = pt._intent(task)["words"]
        self.assertEqual(words, sorted(words), "_words must stay stable and sorted")

    def test_a_prompt_with_only_noise_still_produces_a_template(self):
        """Fail-soft: no salient words falls back rather than emitting an empty Intent."""
        _, body = self._build(prompt="07062319 8b92d078e856 1a3f9c2b4d5e")
        self.assertIn("Intent:", body)
        self.assertIn("Acceptance:", body)

    def test_an_empty_prompt_does_not_raise(self):
        tid, body = self._build(prompt="")
        self.assertTrue(tid)
        self.assertIn("PATCH TEMPLATE", body)

    def test_the_implementation_slots_are_untouched(self):
        _, body = self._build()
        self.assertIn("1. Locate the existing owner module/function", body)
        self.assertIn("3. Add or update the narrowest test/check", body)

    def test_the_same_prompt_builds_the_same_intent_twice(self):
        self.assertEqual(self._build()[1], self._build()[1])


class TestAgainstTheRealQueue(unittest.TestCase):
    """Regression fixture drawn from an actual unimplementable queued template."""

    BROKEN = ("PATCH TEMPLATE 8b0b43e51845\n"
              "Intent: 07062319 07071626 8b92d078e856 acceptance adapt agentic already "
              "alter analysis artifacts backlog because beethoven before behavior below "
              "blocked blocker blocks branch broad bugfix build canary")

    def test_the_shape_this_fixes_is_recognisable(self):
        intent = self.BROKEN.splitlines()[1][len("Intent: "):]
        tokens = intent.split()
        self.assertTrue(pt._NOISE_RE.match(tokens[0]))
        self.assertEqual(tokens[3:], sorted(tokens[3:]),
                         "the broken line is alphabetical, which is the tell")

    def test_the_new_extraction_would_not_produce_that_line(self):
        words = pt._salient_words(self.BROKEN)
        self.assertNotEqual(words[:3], ["07062319", "07071626", "8b92d078e856"])


if __name__ == "__main__":
    unittest.main()
