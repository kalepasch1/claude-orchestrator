#!/usr/bin/env python3
"""runner/preflight_filter.py — the pre-dispatch triage, under test.

This module decides which queued work is allowed to exist. It shipped with no test
file, which is the worst place in the fleet to have none: every verdict it returns
DESTROYS a task, and a wrong verdict fails nothing — the task simply disappears.

Its own source records what that costs. The 2026-08-15 note in `_preflight_check_inner`
audits 139 real tasks quarantined by the attempt-count rule alone, prompt lengths 1,311
to 25,230 characters, median 5,985, not one a garbage stub — "most of the cowork lane's
45% completion rate". The fix was to require BOTH repeated failure AND a thin prompt.
Nothing asserted that fix, so nothing would notice it being undone.

These tests pin the four corrections the source argues for, in the order the module
applies them:

  * a substantial prompt is NOT condemned by attempt count alone (the 139-task rule)
  * a hard ceiling still exists, so nothing retries forever
  * "PATCH TEMPLATE" quoted inside a long real prompt is reuse, not garbage
    (the 2026-07-31 note: 10 real 5KB prompts lost to that false positive)
  * blocker keywords only quarantine when there is genuinely no code target
"""
from __future__ import annotations

import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

import preflight_filter as pf  # noqa: E402

SUBSTANTIAL = ("Implement the retry backoff in runner/account_pool.py: read the cooldown "
               "from config_consumer, clamp it to the documented ceiling, and add a unit "
               "test that proves a malformed value falls back instead of raising. "
               ) * 6

THIN = "fix it"


def task(**over):
    base = {"slug": "demo", "prompt": SUBSTANTIAL, "note": "", "attempt": 0}
    base.update(over)
    return base


class EnvIsolatedTestCase(unittest.TestCase):
    KEYS = ("ORCH_PREFLIGHT_MAX_ATTEMPTS", "ORCH_PREFLIGHT_HARD_CEILING",
            "ORCH_PREFLIGHT_SUBSTANTIAL_CHARS")

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in self.KEYS}
        for key in self.KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AttemptRuleTest(EnvIsolatedTestCase):
    """The 139-task rule. Attempt count alone must not condemn a real spec."""

    def test_a_substantial_prompt_survives_repeated_failure(self):
        self.assertGreater(len(SUBSTANTIAL.strip()), 500, "fixture must be substantial")
        for attempt in (4, 6, 11):
            self.assertEqual(pf.preflight_check(task(attempt=attempt)), "",
                             f"a {len(SUBSTANTIAL)}-char spec was quarantined at "
                             f"attempt {attempt} — this is the 139-task regression")

    def test_a_thin_prompt_that_keeps_failing_is_still_quarantined(self):
        reason = pf.preflight_check(task(prompt=THIN, attempt=4))
        self.assertIn("exhausted", reason)

    def test_a_thin_prompt_under_the_cap_survives_the_attempt_rule(self):
        """It may still fail the too-short rule; it must not fail the attempt rule."""
        reason = pf.preflight_check(task(prompt=THIN, attempt=1))
        self.assertNotIn("exhausted", reason)

    def test_the_hard_ceiling_still_stops_a_substantial_prompt(self):
        reason = pf.preflight_check(task(attempt=12))
        self.assertIn("hard ceiling", reason)

    def test_the_ceiling_is_inclusive_and_the_step_below_it_passes(self):
        self.assertEqual(pf.preflight_check(task(attempt=11)), "")
        self.assertIn("hard ceiling", pf.preflight_check(task(attempt=12)))

    def test_the_thresholds_are_operator_tunable(self):
        os.environ["ORCH_PREFLIGHT_HARD_CEILING"] = "5"
        self.assertIn("hard ceiling", pf.preflight_check(task(attempt=5)))

    def test_the_substantial_threshold_is_operator_tunable(self):
        os.environ["ORCH_PREFLIGHT_SUBSTANTIAL_CHARS"] = "999999"
        self.assertIn("exhausted", pf.preflight_check(task(attempt=4)),
                      "raising the bar must make a formerly-substantial prompt thin")


class GarbagePromptTest(EnvIsolatedTestCase):
    """A genuine stub has the marker near the top of a SHORT body."""

    def test_a_bare_patch_template_stub_is_quarantined(self):
        reason = pf.preflight_check(task(prompt="PATCH TEMPLATE e47542c3d860"))
        self.assertIn("PATCH TEMPLATE", reason)

    def test_a_quoted_patch_template_deep_in_a_real_prompt_survives(self):
        """The 2026-07-31 false positive that cost 10 real 5KB prompts."""
        prompt = SUBSTANTIAL + "\n\nPrior intent: PATCH TEMPLATE e47542c3d860\n" + SUBSTANTIAL
        self.assertEqual(pf.preflight_check(task(prompt=prompt)), "")

    def test_an_empty_prompt_is_quarantined(self):
        self.assertNotEqual(pf.preflight_check(task(prompt="")), "")

    def test_a_whitespace_only_prompt_is_quarantined(self):
        self.assertNotEqual(pf.preflight_check(task(prompt="   \n\n  ")), "")


class RecycledNoteTest(EnvIsolatedTestCase):
    def test_a_recycled_note_is_quarantined(self):
        for note in ("sentinel-dedupe", "queue-bankruptcy", "preflight: already killed",
                     "non-actionable: nope", "GC: reaped"):
            reason = pf.preflight_check(task(note=note))
            self.assertIn("recycled", reason, note)

    def test_an_ordinary_note_is_not(self):
        self.assertEqual(pf.preflight_check(task(note="agentic-repair:rework")), "")

    def test_should_skip_note_matches_the_same_family(self):
        self.assertTrue(pf.should_skip_note("sentinel-dedupe fired"))
        self.assertFalse(pf.should_skip_note("agentic-repair:rework"))


class BlockerCategoryTest(EnvIsolatedTestCase):
    def test_a_bare_legal_ask_with_no_code_target_is_quarantined(self):
        reason = pf.preflight_check(task(prompt="Review the GDPR privacy policy."))
        self.assertNotEqual(reason, "")

    def test_a_security_ask_that_names_a_file_is_dispatchable(self):
        prompt = ("Rotate the API key handling in runner/config_consumer.py: read the "
                  "credential from the environment, never from fleet_config, and add a "
                  "test module that proves a missing value degrades instead of raising. "
                  "Update the schema migration and the endpoint handler accordingly.")
        self.assertEqual(pf.preflight_check(task(prompt=prompt)), "",
                         "a security task with a concrete code target is real work")

    def test_a_metadata_only_prompt_is_quarantined(self):
        prompt = ("## ORCHESTRATION PIPELINE CONTRACT\n"
                  "- source: preflight-gate\n"
                  "- project: beethoven\n"
                  "- task class: mechanical\n"
                  "- strategy planner: local\n")
        self.assertNotEqual(pf.preflight_check(task(prompt=prompt)), "")


class FailSoftTest(EnvIsolatedTestCase):
    def test_it_never_raises_on_a_malformed_task(self):
        for bad in ({}, {"prompt": None}, {"prompt": 5, "attempt": "many"},
                    {"note": None, "prompt": SUBSTANTIAL}):
            try:
                verdict = pf.preflight_check(bad)
            except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                self.fail(f"preflight_check raised {type(exc).__name__}: {exc}")
            self.assertIsInstance(verdict, str)

    def test_a_malformed_threshold_degrades_instead_of_killing_the_batch(self):
        """preflight_check is called inside apply_to_batch's loop with no guard, so a
        raise here does not degrade the gate — it kills the whole batch dispatch."""
        for key in self.KEYS:
            os.environ[key] = "not-a-number"
        self.assertEqual(pf.preflight_check(task(attempt=3)), "")

    def test_a_string_attempt_from_the_database_does_not_raise(self):
        self.assertEqual(pf.preflight_check(task(attempt="3")), "")
        self.assertIn("hard ceiling", pf.preflight_check(task(attempt="12")))

    def test_an_unparseable_attempt_is_treated_as_zero(self):
        """Fail open: a bad row must never cause a wrongful quarantine."""
        self.assertEqual(pf.preflight_check(task(attempt="many")), "")

    def test_a_negative_threshold_falls_back(self):
        os.environ["ORCH_PREFLIGHT_HARD_CEILING"] = "-1"
        self.assertEqual(pf.preflight_check(task(attempt=3)), "")


class ApplyToBatchTest(EnvIsolatedTestCase):
    def test_it_separates_dispatchable_from_killed(self):
        batch = [task(slug="good"), task(slug="stub", prompt="PATCH TEMPLATE abc123f")]
        dispatchable, killed = pf.apply_to_batch(batch)
        self.assertEqual([t["slug"] for t in dispatchable], ["good"])
        self.assertEqual(killed, 1)

    def test_the_quarantine_callback_receives_the_reason(self):
        seen = []
        pf.apply_to_batch([task(slug="stub", prompt="PATCH TEMPLATE abc123f")],
                          quarantine_fn=lambda t, r: seen.append((t["slug"], r)))
        self.assertEqual(len(seen), 1)
        self.assertIn("PATCH TEMPLATE", seen[0][1])

    def test_a_failing_quarantine_callback_keeps_the_task_dispatchable(self):
        """Fail-soft: if we cannot record the kill, we must not silently drop the work."""
        def boom(t, r):
            raise RuntimeError("db down")

        dispatchable, killed = pf.apply_to_batch(
            [task(slug="stub", prompt="PATCH TEMPLATE abc123f")], quarantine_fn=boom)
        self.assertEqual([t["slug"] for t in dispatchable], ["stub"])
        self.assertEqual(killed, 0)

    def test_an_empty_batch_is_handled(self):
        self.assertEqual(pf.apply_to_batch([]), ([], 0))


if __name__ == "__main__":
    unittest.main()
