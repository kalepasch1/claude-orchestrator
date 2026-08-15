#!/usr/bin/env python3
"""Regression tests for blocker_quarantine.classify().

WHY THESE EXIST (2026-08-03)
    classify() decides which repair a blocked task gets, and the repair it picks names the task
    it spawns. When a category can be inferred from the task's own NAME rather than from what
    actually failed, the pipeline enters a closed loop: recover-missing-branch-foo fails for any
    reason -> its prompt contains "recover-missing-branch" -> _MISSING matches -> classified
    missing-branch -> spawns recover-missing-branch-foo again -> matches again. It only ever
    terminates on the depth cap.

    That single path produced 84 of the fleet's repair spawns in one three-hour window and was a
    principal contributor to a backlog of ~2,000 queued and ~700 quarantined tasks. The same hole
    had already been found and fixed once for secret/security; missing-branch kept it because
    classify() concatenated the RAW prompt back onto the evidence-stripped blocker signal.

    Two defences, both tested here:
      1. Specific  — missing-branch reads from evidence only, and the prompt is slug-stripped.
      2. General   — any verdict still reachable with note and log_tail blanked came from the
                     task's identity, not its failure, and is downgraded to "rework".

    Run: python3 test_blocker_classification.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blocker_quarantine as bq

CASES = [
    ("recovery task that really failed the build",
     {"slug": "recover-missing-branch-ioi-lifecycle-slice-1",
      "prompt": "recover-missing-branch-ioi-lifecycle-slice-1: restore the branch",
      "note": "nuxt build failed: Could not load @vercel/analytics/nuxt",
      "log_tail": "npm run build exited 1"},
     "buildfail"),

    ("recovery task that really failed its tests",
     {"slug": "recover-missing-branch-foo",
      "prompt": "recover-missing-branch-foo: restore the branch",
      "note": "tests failed: 3 assertions", "log_tail": ""},
     "testfail"),

    ("genuine missing branch, proven by evidence",
     {"slug": "qafix-tomorrow-123", "prompt": "fix the failing suite",
      "note": "branch agent/qafix-tomorrow-123 no longer exists on origin", "log_tail": ""},
     "missing-branch"),

    ("agent produced no diff",
     {"slug": "improve-thing", "prompt": "improve the thing",
      "note": "agent produced no committable changes", "log_tail": ""},
     "noop"),

    ("name alone must never decide a category",
     {"slug": "recover-missing-branch-x", "prompt": "recover-missing-branch-x",
      "note": "", "log_tail": ""},
     "rework"),

    ("a project literally named 'secret' is not secret work",
     {"slug": "improve-secret-santa-checkout", "prompt": "improve secret-santa checkout",
      "note": "tests failed: 2 assertions", "log_tail": ""},
     "testfail"),
]


def main():
    failures = []
    for label, task, expected in CASES:
        got = bq.classify(task)
        if got != expected:
            failures.append((label, expected, got))
        print("  %s  %-46s expected=%-14s got=%s"
              % ("PASS" if got == expected else "FAIL", label[:46], expected, got))

    print()
    if failures:
        print("FAILED (%d):" % len(failures))
        for label, expected, got in failures:
            print("  - %s: expected %s, got %s" % (label, expected, got))
        print("\nA failure here means a blocked task can be classified from its own name again, "
              "which respawns itself indefinitely. Do not silence this by changing the expected "
              "value — fix the classifier so the verdict comes from the failure evidence.")
        return 1
    print("all %d classification invariants hold" % len(CASES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
