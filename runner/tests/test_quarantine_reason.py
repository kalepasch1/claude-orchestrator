#!/usr/bin/env python3
"""Tests for runner/quarantine_reason.py.

The value of a reason is that it names one remedy, so the tests that matter are
the ones separating reasons whose text overlaps. A stale snapshot and a genuine
test failure both print "test failed"; a missing module and a broken build both
fail the build. Getting those wrong sends the expensive remedy (rework the
source) where the cheap one (regenerate the fixture, install the dep) was
needed, which is the loop this module exists to break.

Real note text from this repository is used wherever possible — inventing
tidier strings than the fleet actually writes is how a classifier passes its
tests and fails in production.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quarantine_reason as qr  # noqa: E402


class TestTheFiveNamedReasons(unittest.TestCase):
    def test_merge_conflict(self):
        for text in [
            "train: still conflicts after 4 redos - needs manual rebase. "
            "Conflicting files: packages/darwin-kernel/src/passport/passport.ts.",
            "CONFLICT (content): Merge conflict in runner/db.py",
            "Automatic merge failed; fix conflicts and then commit the result.",
        ]:
            self.assertEqual(qr.classify(text), qr.MERGE_CONFLICT, msg=text[:50])

    def test_test_timeout(self):
        for text in [
            "Error: Hook timed out in 10000ms",
            "test suite exceeded timeout of 60000 ms",
            '{"subtype":"error_max_turns","is_error":true}',
            "ETIMEDOUT connecting to fixture server",
        ]:
            self.assertEqual(qr.classify(text), qr.TEST_TIMEOUT, msg=text[:50])

    def test_missing_dependency(self):
        for text in [
            "ERR_MODULE_NOT_FOUND: Cannot find package 'vitest'",
            "ModuleNotFoundError: No module named 'pytest'",
            "sh: vercel: command not found",
            "Could not resolve dependency: @nuxt/kit",
        ]:
            self.assertEqual(qr.classify(text), qr.MISSING_DEPENDENCY, msg=text[:50])

    def test_pre_merge_gate_fail(self):
        for text in [
            "merge-train-regression-guard: quarantined as regressfail after 3 attempts",
            "The public-copy disclosure QA gate is RED and is BLOCKING release.",
            "pre-merge gate blocked: convention-lint regression on HARDCODED_SECRET",
        ]:
            self.assertEqual(qr.classify(text), qr.PRE_MERGE_GATE_FAIL, msg=text[:50])

    def test_fixture_stale(self):
        for text in [
            "1 snapshot failed. Run with -u to update.",
            "obsolete snapshot found in __snapshots__/panel.test.ts.snap",
            "fixture is stale: regenerate with npm run gen:types",
        ]:
            self.assertEqual(qr.classify(text), qr.FIXTURE_STALE, msg=text[:50])


class TestOrderingSeparatesOverlappingText(unittest.TestCase):
    """Where two rules could both fire, the cheaper remedy has to win."""

    def test_a_stale_snapshot_that_also_says_test_failed(self):
        text = ("FAIL  components/__tests__/panel.test.ts\n"
                "  × renders the panel > toMatchSnapshot\n"
                "  1 test failed, 1 snapshot mismatch. Run with -u to update.")
        self.assertEqual(qr.classify(text), qr.FIXTURE_STALE)

    def test_a_missing_module_that_also_fails_the_build(self):
        text = ("build failed\n"
                "ERR_MODULE_NOT_FOUND: Cannot find package 'vitest' imported from "
                "/repo-wt/slug/vitest.config.ts")
        self.assertEqual(qr.classify(text), qr.MISSING_DEPENDENCY)

    def test_a_timeout_inside_a_conflict_note_is_still_a_conflict(self):
        # The conflict is the thing that must be fixed; the timeout is downstream.
        text = "needs manual rebase; the retry then timed out after 60000ms"
        self.assertEqual(qr.classify(text), qr.MERGE_CONFLICT)


class TestTheFleetsOwnUntaggedNotes(unittest.TestCase):
    """The notes that currently land in "(unparsed)" and need manual reading."""

    def test_repair_ceiling_note(self):
        note = ("repair-ceiling: orphaned-running after 9 repairs without reaching a "
                "completed state. attempt=1. Repair is not converging; parked for "
                "review rather than re-queued.")
        self.assertEqual(qr.classify(note), qr.REPAIR_CEILING)

    def test_missing_branch_note(self):
        note = "recovery: no agent branch and no commit anywhere names this slug"
        self.assertEqual(qr.classify(note), qr.MISSING_BRANCH)

    def test_infra_note(self):
        note = "worker process exited: out of memory while running the suite"
        self.assertEqual(qr.classify(note), qr.INFRA)

    def test_a_note_with_nothing_in_it_is_honestly_unknown(self):
        # Better an admitted gap than a confident wrong remedy.
        self.assertEqual(qr.classify("parked for review"), qr.UNKNOWN)
        self.assertEqual(qr.classify(""), qr.UNKNOWN)
        self.assertEqual(qr.classify(None), qr.UNKNOWN)


class TestAdministrativeParks(unittest.TestCase):
    """Most quarantine is housekeeping, not breakage.

    Against beethoven's 575 live QUARANTINED rows the first version of this
    module returned `unknown` for 91.3%, because it only knew how to name
    failures. The actual distribution is dominated by integration_sweeper (196),
    GC (173), recovery_dedup (56), spec-lost (36), queue-bankruptcy (21) and
    semantic-dedupe (20). Every note below is real.
    """

    def test_dedup_parks(self):
        for note in [
            "recovery_dedup: superseded by a newer recovery task for the same slug",
            "semantic-dedupe: 0.990 duplicate of reconcile-conflict-dropbox-mission",
        ]:
            self.assertEqual(qr.classify(note), qr.DUPLICATE, msg=note[:40])

    def test_a_gc_note_that_is_really_a_duplicate_reads_as_duplicate(self):
        # The commonest GC note opens with the sweeper's prefix but the reason
        # is the duplication. If SWEPT_STALE were ordered first it would take
        # 173 rows and describe them wrongly.
        note = ("GC: semantic-dedupe: 0.992 duplicate of "
                "improve-automate-branch-management-with-git-auto-slice-2")
        self.assertEqual(qr.classify(note), qr.DUPLICATE)

    def test_sweeper_parks(self):
        note = ("integration_sweeper: branch lost and recovery exhausted; "
                "closed to stop phantom missing_branch churn")
        self.assertEqual(qr.classify(note), qr.SWEPT_STALE)

    def test_spec_lost(self):
        note = ("spec-lost: the task prompt was overwritten with the "
                "\"Complete the task '<slug>'.\" stub by the narrow-select repair "
                "bug (fixed 2026-08-03). The original specification is not "
                "recoverable from this row.")
        self.assertEqual(qr.classify(note), qr.SPEC_LOST)

    def test_degenerate_prompt(self):
        for note in [
            "preflight: PATCH TEMPLATE or garbage prompt (auto-quarantine)",
            "cowork-executor-v6.5: hex-only PATCH TEMPLATE stub (per gate 3a).",
            "v6.5: degenerate PATCH TEMPLATE stub — no readable implementation intent.",
        ]:
            self.assertEqual(qr.classify(note), qr.DEGENERATE_PROMPT, msg=note[:40])

    def test_queue_bankruptcy(self):
        note = ("queue-bankruptcy: original task dropbox-wave-c-compounding-codegen "
                "is already DONE/MERGED")
        self.assertEqual(qr.classify(note), qr.QUEUE_BANKRUPTCY)

    def test_stuck_reaper_is_a_repair_ceiling(self):
        note = ("stuck-reaper: quarantined after 3 stuck cycles (preventing credit "
                "burn). diagnosis=death_loop. agentic-repair:rework")
        self.assertEqual(qr.classify(note), qr.REPAIR_CEILING)

    def test_a_fast_forward_refusal_is_a_merge_conflict(self):
        note = ("blocker-quarantine: quarantined as secret; replacement queued as "
                "rework-secret-x. Original blocker: train: base won't fast-forward "
                "after 4 redos")
        self.assertEqual(qr.classify(note), qr.MERGE_CONFLICT)

    def test_administrative_reasons_prescribe_no_investigation(self):
        # The point of naming these is to STOP sending humans at them.
        for reason in (qr.DUPLICATE, qr.SWEPT_STALE):
            self.assertTrue(qr.remedy_for(reason).startswith("none"), msg=reason)


class TestLegacyCategoryFallback(unittest.TestCase):
    """Notes written before the tag must not all read as unknown on day one."""

    def test_legacy_conflict_category_maps_to_merge_conflict(self):
        note = "blocker-quarantine: quarantined as conflict; replacement queued as x-2."
        self.assertEqual(qr.classify(note), qr.MERGE_CONFLICT)

    def test_legacy_missing_branch_category(self):
        note = "blocker-quarantine: quarantined as missing-branch; replacement queued as x."
        self.assertEqual(qr.classify(note), qr.MISSING_BRANCH)

    def test_the_failure_text_outranks_the_legacy_category(self):
        # A category is a coarser guess than the actual error; evidence wins.
        note = ("blocker-quarantine: quarantined as conflict; replacement queued as x. "
                "Original blocker: ModuleNotFoundError: No module named 'db'")
        self.assertEqual(qr.classify(note), qr.MISSING_DEPENDENCY)

    def test_an_unmapped_legacy_category_does_not_invent_a_reason(self):
        note = "blocker-quarantine: quarantined as rework; replacement queued as x."
        self.assertEqual(qr.classify(note), qr.UNKNOWN)


class TestTheTag(unittest.TestCase):
    def test_round_trips(self):
        tagged = qr.tag("some note", qr.MERGE_CONFLICT)
        self.assertEqual(qr.parse(tagged), qr.MERGE_CONFLICT)
        self.assertIn("some note", tagged)

    def test_is_idempotent_and_never_leaves_two_tags(self):
        once = qr.tag("n", qr.TEST_TIMEOUT)
        twice = qr.tag(once, qr.TEST_TIMEOUT)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("[quarantine-reason:"), 1)

    def test_retagging_replaces_rather_than_appends(self):
        first = qr.tag("n", qr.TEST_TIMEOUT)
        second = qr.tag(first, qr.FIXTURE_STALE)
        self.assertEqual(second.count("[quarantine-reason:"), 1)
        self.assertEqual(qr.parse(second), qr.FIXTURE_STALE)

    def test_an_unknown_reason_is_stored_as_unknown_not_invented(self):
        tagged = qr.tag("n", "definitely_not_a_reason")
        self.assertEqual(qr.parse(tagged), qr.UNKNOWN)

    def test_parse_returns_none_for_an_untagged_note(self):
        self.assertIsNone(qr.parse("blocker-quarantine: quarantined as conflict;"))
        self.assertIsNone(qr.parse(""))
        self.assertIsNone(qr.parse(None))

    def test_an_explicit_tag_outranks_the_patterns(self):
        # The writer knew something the text does not say.
        note = qr.tag("Cannot find module 'x'", qr.FIXTURE_STALE)
        self.assertEqual(qr.classify(note), qr.FIXTURE_STALE)

    def test_tagging_an_empty_note_still_yields_a_readable_tag(self):
        self.assertEqual(qr.parse(qr.tag("", qr.INFRA)), qr.INFRA)


class TestAnnotate(unittest.TestCase):
    def test_classifies_and_tags_in_one_call(self):
        note = "blocker-quarantine: quarantined as buildfail; replacement queued as x."
        out = qr.annotate(note, "ERR_MODULE_NOT_FOUND: Cannot find package 'vitest'")
        self.assertEqual(qr.parse(out), qr.MISSING_DEPENDENCY)
        self.assertIn("blocker-quarantine", out)

    def test_the_note_itself_counts_as_evidence(self):
        out = qr.annotate("needs manual rebase")
        self.assertEqual(qr.parse(out), qr.MERGE_CONFLICT)


class TestEveryReasonNamesARemedy(unittest.TestCase):
    """A reason nobody can act on is the prose problem with better punctuation."""

    def test_every_reason_has_a_distinct_non_empty_remedy(self):
        remedies = [qr.remedy_for(r) for r in qr.REASONS]
        for r, remedy in zip(qr.REASONS, remedies):
            self.assertTrue(remedy.strip(), msg=r)
        self.assertEqual(len(set(remedies)), len(remedies))

    def test_the_taxonomy_is_closed(self):
        self.assertEqual(len(qr.REASONS), len(set(qr.REASONS)))
        for r in qr.REASONS:
            self.assertIn(r, qr.REMEDIES)
        for r in qr.REMEDIES:
            self.assertIn(r, qr.REASONS)

    def test_the_five_reasons_the_brief_named_are_all_present(self):
        for r in (qr.MERGE_CONFLICT, qr.TEST_TIMEOUT, qr.MISSING_DEPENDENCY,
                  qr.PRE_MERGE_GATE_FAIL, qr.FIXTURE_STALE):
            self.assertIn(r, qr.REASONS)

    def test_an_unrecognised_reason_falls_back_to_the_unknown_remedy(self):
        self.assertEqual(qr.remedy_for("nope"), qr.REMEDIES[qr.UNKNOWN])


if __name__ == "__main__":
    unittest.main(verbosity=2)
