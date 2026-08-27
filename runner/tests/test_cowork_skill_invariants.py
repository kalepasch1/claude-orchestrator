import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cowork_skill_invariants as inv

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILL_DIR = os.path.join(REPO_ROOT, "cowork-skills")

# The wording every skill must carry. Kept as one block so a skill that drifts
# can be repaired by pasting it back, and so the test states the requirement
# rather than merely detecting it.
COMPLIANT_PREFLIGHT = """
Before treating a zero-row claim as an empty queue, count QUEUED separately from
claimable. If queued > 0 and claimable = 0 that is a STALL, not an empty queue,
and it is never a reason to stop.
"""

# A skill body carrying the other four invariants, so preflight tests vary one
# thing at a time.
OTHER_INVARIANTS = """
NEVER read GITHUB_PAT from fleet_config.
Do not run git remote set-url origin with an injected token.
No stub commits: DONE only after a verified push.
"""


def _skill_files():
    if not os.path.isdir(SKILL_DIR):
        return []
    return sorted(
        os.path.join(SKILL_DIR, f)
        for f in os.listdir(SKILL_DIR)
        if f.endswith(".SKILL.md")
    )


class TestClaimabilityPreflight(unittest.TestCase):
    """The check that would have caught the 2026-07-15 -> 2026-08-27 silent stall."""

    def test_compliant_text_passes(self):
        self.assertTrue(inv.has_claimability_preflight(COMPLIANT_PREFLIGHT))

    def test_the_exact_broken_wording_fails(self):
        """The line sixteen executors ran for six weeks."""
        broken = "If 0 rows -> heartbeat (Step 4), write `<run-summary>`, stop."
        self.assertFalse(inv.has_claimability_preflight(broken))

    def test_mentioning_claimable_alone_is_not_enough(self):
        """Naming the concept without comparing counts leaves the bug in place."""
        self.assertFalse(
            inv.has_claimability_preflight("Claim up to 5 claimable tasks and stop.")
        )

    def test_line_wrapping_does_not_break_detection(self):
        """Sixteen hand-edited copies wrap differently; that is not a regression."""
        wrapped = "...count QUEUED separately from\nclaimable. If queued > 0\nand claimable = 0 ..."
        self.assertTrue(inv.has_claimability_preflight(wrapped))

    def test_case_insensitive(self):
        self.assertTrue(
            inv.has_claimability_preflight("QUEUED > 0 AND CLAIMABLE = 0 IS A STALL")
        )


class TestFalseEmptyExitProhibition(unittest.TestCase):
    def test_compliant_text_passes(self):
        self.assertTrue(inv.forbids_false_empty_exit(COMPLIANT_PREFLIGHT))

    def test_preflight_without_prohibition_fails(self):
        """Counting the stall but still exiting on it is the same silent failure."""
        text = "Count queued > 0 and claimable separately, then stop."
        self.assertTrue(inv.has_claimability_preflight(text))
        self.assertFalse(inv.forbids_false_empty_exit(text))


class TestLegacyInvariants(unittest.TestCase):
    """README invariants 1, 2 and 5 — regressions here have already cost runs."""

    def test_credential_rule_detected(self):
        self.assertTrue(
            inv.forbids_fleet_config_credentials("NEVER read GITHUB_PAT from fleet_config")
        )

    def test_credential_rule_absent(self):
        self.assertFalse(
            inv.forbids_fleet_config_credentials("Read GITHUB_PAT from fleet_config.")
        )

    def test_remote_rewrite_rule(self):
        self.assertTrue(inv.forbids_remote_url_rewrite("Do not use git remote set-url"))
        self.assertFalse(inv.forbids_remote_url_rewrite("Run git remote set-url origin ..."))

    def test_remote_rewrite_rule_accepts_the_live_wording(self):
        """The sixteen real skills say this and never say `set-url`.

        Requiring the literal `set-url` failed every compliant file — the exact
        false alarm that gets a checker ignored.
        """
        self.assertTrue(
            inv.forbids_remote_url_rewrite(
                "# DO NOT rewrite origin. It is already correct and "
                "authenticated via osxkeychain."
            )
        )

    def test_stub_commit_rule(self):
        self.assertTrue(inv.forbids_stub_commits("No stub commits."))
        self.assertFalse(inv.forbids_stub_commits("Commit whatever you have."))


class TestCheckSkillAggregation(unittest.TestCase):
    def test_fully_compliant_body_is_ok(self):
        r = inv.check_skill(COMPLIANT_PREFLIGHT + OTHER_INVARIANTS, name="good")
        self.assertTrue(r["ok"], r["failed"])
        self.assertEqual(r["failed"], [])
        self.assertEqual(r["name"], "good")

    def test_failures_are_named(self):
        r = inv.check_skill(OTHER_INVARIANTS, name="no-preflight")
        self.assertFalse(r["ok"])
        self.assertIn("claimability_preflight", r["failed"])
        self.assertIn("no_false_empty_exit", r["failed"])
        # The invariants that ARE present must not be reported as failures.
        self.assertNotIn("no_stub_commits", r["failed"])

    def test_never_raises_on_junk_input(self):
        """A sweep over sixteen files must not die on one unreadable one."""
        for junk in (None, "", 0, [], {"a": 1}):
            r = inv.check_skill(junk, name="junk")
            self.assertIn("ok", r)
            self.assertFalse(r["ok"])

    def test_every_check_has_a_stated_reason(self):
        for name, _pred, _why in inv.CHECKS:
            self.assertTrue(inv.why(name), name)
        self.assertEqual(inv.why("no-such-check"), "")

    def test_check_many_and_report(self):
        results = inv.check_many([
            ("good", COMPLIANT_PREFLIGHT + OTHER_INVARIANTS),
            ("bad", "nothing useful here"),
        ])
        self.assertEqual(len(results), 2)
        lines = inv.format_report(results)
        self.assertTrue(any(l.startswith("ok   good") for l in lines), lines)
        self.assertTrue(any(l.startswith("FAIL bad") for l in lines), lines)
        # A failure line must explain itself, not just name the check.
        self.assertTrue(any("—" in l for l in lines if l.startswith("FAIL")), lines)


class TestVersionedSkillCopies(unittest.TestCase):
    """The point of the module: hold the sixteen real skill files to the line."""

    def test_skill_copies_are_present(self):
        files = _skill_files()
        self.assertTrue(files, "cowork-skills/*.SKILL.md missing — the backup set is gone")

    def test_every_skill_copy_satisfies_every_invariant(self):
        failures = []
        for path in _skill_files():
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            r = inv.check_skill(text, name=os.path.basename(path))
            if not r["ok"]:
                failures.extend(inv.format_report([r]))
        self.assertEqual(failures, [], "\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
