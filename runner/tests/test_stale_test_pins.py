#!/usr/bin/env python3
"""A repin moves source and leaves the tests asserting the old string.

On 2026-08-24, 45afe205 repinned twelve dead model ids and deliberately did not
rewrite tests, reasoning that a test naming a dead model usually pins it on
purpose. That holds for test_provider_banner_exhaustion.py, which pins verbatim
404 text as evidence. It did not hold for tests/test_routing.py, which hardcoded
the DEFAULT VALUE of PREFLIGHT_ESCALATED_MODEL in eight assertions and went red
the moment the constant moved google:gemini-2.0-flash -> google:gemini-2.5-flash.

Nothing caught it. The dead-id audit does not read tests, by design, and a
vendor catalogue has no opinion about what a test expects. `stale_test_pins`
asks the offline question instead -- does any routing code still name this? --
and this file pins the two properties that decide whether its answer is worth
reading: it must find the real desync, and it must stay quiet about fixtures.
"""
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "tools"))

import model_id_audit as mia  # noqa: E402


def _write(root, rel, source):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(source)
    return path


class FamilyTest(unittest.TestCase):
    """Two ids are siblings when they differ only in version."""

    def test_version_tokens_are_dropped(self):
        self.assertEqual(mia._family("gemini-2.0-flash"), "gemini-flash")
        self.assertEqual(mia._family("gemini-2.5-flash"), "gemini-flash")

    def test_siblings_across_a_repin_agree(self):
        self.assertEqual(mia._family("gemini-2.0-flash"),
                         mia._family("gemini-2.5-flash"))

    def test_different_tiers_are_not_siblings(self):
        """The repin moved tiers around; -lite must not collapse into -flash."""
        self.assertNotEqual(mia._family("gemini-2.5-flash"),
                            mia._family("gemini-3.1-flash-lite"))
        self.assertNotEqual(mia._family("gemini-3.1-pro-preview"),
                            mia._family("gemini-3.5-flash"))

    def test_the_two_spellings_of_one_model_agree(self):
        """The fleet writes the same Anthropic model both ways."""
        self.assertEqual(mia._family("claude-haiku-4.5"),
                         mia._family("claude-haiku-4-5-20251001"))

    def test_an_all_version_id_has_no_family(self):
        self.assertEqual(mia._family("4.5"), "")


class StaleTestPinsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def _run(self):
        return mia.stale_test_pins(self.root)

    def test_finds_the_expectation_a_repin_left_behind(self):
        """The 2026-08-24 failure, reproduced in miniature."""
        _write(self.root, "config.py",
               'ESCALATED = "google:gemini-2.5-flash"\n')
        _write(self.root, "tests/test_routing.py",
               'def test_legal():\n'
               '    assert route("legal") == "google:gemini-2.0-flash"\n')

        stale = self._run()

        self.assertIn("gemini-2.0-flash", stale)
        self.assertTrue(any("test_routing.py" in site
                            for site in stale["gemini-2.0-flash"]))

    def test_reports_the_line_so_it_can_be_read_not_just_the_id(self):
        """A bare id list is not actionable; the judgement needs the test."""
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_x.py", 'X = "gemini-2.0-flash"\n')

        sites = self._run()["gemini-2.0-flash"]

        self.assertEqual(sorted(sites), ["tests/test_x.py:1"])

    def test_stays_quiet_about_an_id_source_still_names(self):
        """Not stale: source routes to it, so the test agrees with source."""
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_x.py", 'X = "gemini-2.5-flash"\n')

        self.assertEqual(self._run(), {})

    def test_stays_quiet_about_a_fixture_with_no_sibling(self):
        """`claude-9912` is invented by a test. Reporting it is crying wolf."""
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_x.py", 'X = "grok-9912"\n')

        self.assertEqual(self._run(), {})

    def test_a_deliberate_relic_is_reported_and_that_is_accepted(self):
        """Honest about the false positive this design chooses to keep.

        test_provider_banner_exhaustion.py pins a dead id on purpose, as the
        404 evidence it exists to preserve. It has a live sibling, so it shows
        up here. That is why the mode reports and never repins: telling a
        relic from a stale expectation is a judgement about what the test is
        FOR, which no rule in this file can make.
        """
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_banner.py",
               'DEAD_404 = "gemini-2.0-flash"  # pinned as evidence\n')

        self.assertIn("gemini-2.0-flash", self._run())

    def test_source_is_read_from_source_only(self):
        """Two tests agreeing with each other must not count as source."""
        _write(self.root, "tests/test_a.py", 'A = "gemini-2.0-flash"\n')
        _write(self.root, "tests/test_b.py", 'B = "gemini-2.5-flash"\n')

        self.assertEqual(self._run(), {})

    def test_docstrings_and_comments_are_not_pins(self):
        """Inherited from scan(): an id in prose is not an expectation."""
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_x.py",
               '"""We used to route to gemini-2.0-flash here."""\n'
               '# and gemini-2.0-flash again\n')

        self.assertEqual(self._run(), {})


class ScanIsUnchangedTest(unittest.TestCase):
    """The dead-id path must be byte-for-byte what it was before the split."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.addCleanup(self._tmp.cleanup)

    def test_default_scan_still_excludes_tests(self):
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_x.py", 'X = "gemini-2.0-flash"\n')
        _write(self.root, "test_top_level.py", 'Y = "gemini-3.5-flash"\n')

        found = mia.scan(self.root)

        self.assertIn("gemini-2.5-flash", found)
        self.assertNotIn("gemini-2.0-flash", found)
        self.assertNotIn("gemini-3.5-flash", found)

    def test_tests_scan_is_the_exact_complement(self):
        _write(self.root, "config.py", 'M = "gemini-2.5-flash"\n')
        _write(self.root, "tests/test_x.py", 'X = "gemini-2.0-flash"\n')
        _write(self.root, "conftest.py", 'Z = "gemini-3.5-flash"\n')

        found = mia.scan(self.root, tests=True)

        self.assertIn("gemini-2.0-flash", found)
        self.assertIn("gemini-3.5-flash", found)
        self.assertNotIn("gemini-2.5-flash", found)

    def test_the_audit_never_reads_its_own_source(self):
        """It contains every vendor prefix it searches for, in both modes."""
        _write(self.root, "model_id_audit.py", 'M = "gemini-2.0-flash"\n')
        _write(self.root, "tests/model_id_audit.py", 'M = "gemini-2.0-flash"\n')

        self.assertEqual(mia.scan(self.root), {})
        self.assertEqual(mia.scan(self.root, tests=True), {})


if __name__ == "__main__":
    unittest.main()
