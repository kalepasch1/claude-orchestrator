"""
test_session_proof.py - the proof-of-work verifier must reliably separate real sessions
from blank/stalled ones. All git calls are mocked (no real subprocess).

  A) real diff + engaged output -> ok=True
  B) noise-only diff (.claude/, *.log, settings.local.json) -> ok=False
  C) stall phrases ("what would you like to work on", ...) -> ok=False
  D) prompt-echo: output that ignores the task prompt -> ok=False; short prompts skip the check
  E) tests-passing mention is a bonus reason, never required
  F) reinjection_prompt inlines the FULL original prompt under the explicit header
"""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import session_proof


def _numstat(rows):
    """Build a fake `git diff --numstat` CompletedProcess from (added, deleted, path) rows."""
    out = "".join(f"{a}\t{d}\t{p}\n" for a, d, p in rows)
    return MagicMock(returncode=0, stdout=out, stderr="")


TASK = {
    "slug": "add-webhook-retry",
    "base_branch": "main",
    "prompt": ("Implement exponential backoff retries for the webhook dispatcher module. "
               "Failed deliveries should requeue with jittered delays and a maximum attempt cap."),
}

GOOD_OUTPUT = ("I implemented exponential backoff retries in the webhook dispatcher. "
               "Failed deliveries now requeue with jittered delays and respect the maximum "
               "attempt cap. All tests passed.")


class TestVerifySession(unittest.TestCase):

    # ── A: happy path ────────────────────────────────────────────────────────

    def test_real_work_is_ok(self):
        with patch.object(session_proof.subprocess, "run",
                          return_value=_numstat([(40, 5, "src/webhooks/dispatch.py"),
                                                 (12, 0, "tests/test_dispatch.py")])):
            r = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/add-webhook-retry")
        self.assertTrue(r["ok"], f"expected ok, got reasons={r['reasons']}")
        self.assertEqual(r["diff_files"], 2)
        self.assertEqual(r["diff_lines"], 57)

    # ── B: diff checks ───────────────────────────────────────────────────────

    def test_empty_diff_fails(self):
        with patch.object(session_proof.subprocess, "run", return_value=_numstat([])):
            r = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/x")
        self.assertFalse(r["ok"])
        self.assertEqual(r["diff_files"], 0)
        self.assertTrue(any("no non-noise diff" in reason for reason in r["reasons"]))

    def test_noise_only_diff_fails(self):
        rows = [(3, 0, ".claude/settings.json"),
                (100, 0, "debug.log"),
                (1, 1, "app/settings.local.json")]
        with patch.object(session_proof.subprocess, "run", return_value=_numstat(rows)):
            r = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/x")
        self.assertFalse(r["ok"], "noise-only diff must not count as real work")
        self.assertEqual(r["diff_files"], 0)
        self.assertEqual(r["diff_lines"], 0)

    def test_noise_plus_real_counts_only_real(self):
        rows = [(3, 0, ".claude/settings.json"), (10, 2, "src/core.py")]
        with patch.object(session_proof.subprocess, "run", return_value=_numstat(rows)):
            r = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/x")
        self.assertTrue(r["ok"])
        self.assertEqual(r["diff_files"], 1)
        self.assertEqual(r["diff_lines"], 12)

    def test_binary_numstat_dashes_handled(self):
        rows_proc = MagicMock(returncode=0, stdout="-\t-\tassets/logo.png\n5\t1\tsrc/a.py\n")
        with patch.object(session_proof.subprocess, "run", return_value=rows_proc):
            r = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/x")
        self.assertTrue(r["ok"])
        self.assertEqual(r["diff_files"], 2)

    def test_git_failure_is_treated_as_no_diff(self):
        with patch.object(session_proof.subprocess, "run",
                          return_value=MagicMock(returncode=128, stdout="", stderr="bad rev")):
            r = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/x")
        self.assertFalse(r["ok"])
        self.assertEqual(r["diff_files"], 0)

    # ── C: stall detection ───────────────────────────────────────────────────

    def test_stall_phrases_fail(self):
        stalls = ["Hi! What would you like to work on today?",
                  "I'm ready to help with whatever you need.",
                  "It seems I don't have a specific task assigned."]
        for text in stalls:
            with patch.object(session_proof.subprocess, "run",
                              return_value=_numstat([(10, 0, "src/a.py")])):
                r = session_proof.verify_session(TASK, text, "/repo", "agent/x")
            self.assertFalse(r["ok"], f"stall output must fail: {text!r}")
            self.assertTrue(any("stall" in reason for reason in r["reasons"]))

    def test_stall_detection_is_case_insensitive(self):
        self.assertIsNotNone(session_proof.STALL_RX.search("WHAT WOULD YOU LIKE TO WORK ON?"))

    # ── D: prompt-echo ───────────────────────────────────────────────────────

    def test_unrelated_output_fails_prompt_echo(self):
        with patch.object(session_proof.subprocess, "run",
                          return_value=_numstat([(10, 0, "src/a.py")])):
            r = session_proof.verify_session(TASK, "Refactored the CSS grid and tweaked colors.",
                                             "/repo", "agent/x")
        self.assertFalse(r["ok"])
        self.assertTrue(any("prompt-echo" in reason for reason in r["reasons"]))

    def test_short_prompt_skips_echo_check(self):
        short_task = dict(TASK, prompt="fix the bug")   # < 40 chars
        with patch.object(session_proof.subprocess, "run",
                          return_value=_numstat([(10, 0, "src/a.py")])):
            r = session_proof.verify_session(short_task, "Did something entirely different.",
                                             "/repo", "agent/x")
        self.assertTrue(r["ok"], "short prompts must not trigger the echo check")

    # ── E: tests-passing bonus ───────────────────────────────────────────────

    def test_tests_passing_is_bonus_not_required(self):
        no_tests_output = ("I implemented exponential backoff retries in the webhook "
                           "dispatcher; failed deliveries requeue with jittered delays.")
        with patch.object(session_proof.subprocess, "run",
                          return_value=_numstat([(10, 0, "src/a.py")])):
            r = session_proof.verify_session(TASK, no_tests_output, "/repo", "agent/x")
        self.assertTrue(r["ok"], "missing tests-pass mention must not fail the session")
        self.assertFalse(any(reason.startswith("bonus") for reason in r["reasons"]))

        with patch.object(session_proof.subprocess, "run",
                          return_value=_numstat([(10, 0, "src/a.py")])):
            r2 = session_proof.verify_session(TASK, GOOD_OUTPUT, "/repo", "agent/x")
        self.assertTrue(r2["ok"])
        self.assertTrue(any(reason.startswith("bonus") for reason in r2["reasons"]),
                        "tests-pass mention should add a bonus reason")

    # ── result shape ─────────────────────────────────────────────────────────

    def test_result_shape(self):
        with patch.object(session_proof.subprocess, "run", return_value=_numstat([])):
            r = session_proof.verify_session({}, "", "/repo", "agent/x")
        self.assertEqual(set(r.keys()), {"ok", "reasons", "diff_files", "diff_lines"})
        self.assertIsInstance(r["ok"], bool)
        self.assertIsInstance(r["reasons"], list)


class TestReinjectionPrompt(unittest.TestCase):

    def test_header_and_full_prompt_inlined(self):
        p = session_proof.reinjection_prompt(TASK)
        self.assertIn("YOUR TASK (previous session received no instructions — do this now):", p)
        self.assertIn(TASK["prompt"], p, "the FULL original prompt must be inlined")
        self.assertIn("agent/add-webhook-retry", p)

    def test_header_comes_first(self):
        p = session_proof.reinjection_prompt(TASK)
        self.assertTrue(p.startswith("YOUR TASK"))
        self.assertLess(p.index("YOUR TASK"), p.index(TASK["prompt"][:30]))

    def test_handles_missing_fields(self):
        p = session_proof.reinjection_prompt({})
        self.assertIn("YOUR TASK", p)
        p2 = session_proof.reinjection_prompt(None)
        self.assertIn("YOUR TASK", p2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
