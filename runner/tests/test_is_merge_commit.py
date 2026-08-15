#!/usr/bin/env python3
"""Unit tests for the is_merge_commit() message heuristic.

The example messages are taken from this repository's own log and from GitHub's merge
format, not invented — the point of a message heuristic is that it matches what the
tools actually emit.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bot_commit_verifier import is_merge_commit


class GitMergeSubjectsTest(unittest.TestCase):
    """Standard git merge commits."""

    def test_plain_git_merge(self):
        self.assertTrue(is_merge_commit("Merge branch 'agent/qafix-tomorrow-07062319'"))

    def test_git_merge_into_target(self):
        self.assertTrue(is_merge_commit("Merge branch 'orchestrator/dev' into master"))

    def test_fleet_auto_resolved_merge(self):
        # auto_conflict_resolver.py writes exactly this shape.
        self.assertTrue(is_merge_commit("Merge branch 'agent/x' (auto-resolved)"))

    def test_remote_tracking_merge_is_a_documented_gap(self):
        # git writes "Merge remote-tracking branch 'origin/master'" — a real merge whose
        # subject contains NEITHER named phrase contiguously, so the specified contract
        # ('Merge branch' or 'Merge pull request') returns False. Recorded as a test so
        # the gap is visible and any future widening of the pattern is deliberate.
        self.assertFalse(is_merge_commit("Merge remote-tracking branch 'origin/master'"))

    def test_multiline_merge_body(self):
        msg = ("Merge branch 'agent/host-update-failure-must-be-loud'\n"
               "\n"
               "Conflicts:\n"
               "\trunner/fleet_control.py\n")
        self.assertTrue(is_merge_commit(msg))

    def test_merge_header_not_on_the_first_line(self):
        # The merge train prepends context; anchoring to ^ would miss these.
        msg = "train: integrate slice 4\n\nMerge branch 'agent/slice-4' into master\n"
        self.assertTrue(is_merge_commit(msg))


class PullRequestSubjectsTest(unittest.TestCase):
    """GitHub merge commits."""

    def test_github_pull_request(self):
        self.assertTrue(is_merge_commit("Merge pull request #42 from kalepasch1/agent/x"))

    def test_github_pull_request_with_title_body(self):
        msg = ("Merge pull request #1337 from kalepasch1/agent/batch-fusion\n"
               "\n"
               "feat(fusion): un-pause batch fusion")
        self.assertTrue(is_merge_commit(msg))


class NonMergeCommitsTest(unittest.TestCase):
    """Ordinary commits must not be classified as merges."""

    def test_conventional_commit(self):
        self.assertFalse(is_merge_commit("fix(slicer): refuse to slice a prompt with no intent"))

    def test_agent_commit(self):
        self.assertFalse(is_merge_commit("agent: recover-missing-branch-crashloop-costslo"))

    def test_the_word_merge_alone_is_not_enough(self):
        self.assertFalse(is_merge_commit("chore: merge the two config loaders"))

    def test_merged_past_tense_is_not_a_merge_header(self):
        self.assertFalse(is_merge_commit("docs: describe how branches get merged"))

    def test_branch_alone_is_not_enough(self):
        self.assertFalse(is_merge_commit("feat: create the agent branch automatically"))

    def test_pull_alone_is_not_enough(self):
        self.assertFalse(is_merge_commit("fix(fleet): record every git pull outcome"))

    def test_rebase_is_not_a_merge(self):
        self.assertFalse(is_merge_commit("Rebase branch 'agent/x' onto master"))

    def test_revert_of_a_merge_is_still_reported_by_its_text(self):
        # git's own revert subject quotes the reverted subject, so the phrase is present.
        # Documented behavior rather than an accident: callers wanting true reverts
        # excluded must check for the Revert prefix themselves.
        self.assertTrue(is_merge_commit('Revert "Merge branch \'agent/x\'"'))


class EmptyAndNoneInputTest(unittest.TestCase):
    """Fail-soft: a missing message is not a merge, and never raises."""

    def test_empty_string(self):
        self.assertFalse(is_merge_commit(""))

    def test_none(self):
        self.assertFalse(is_merge_commit(None))

    def test_whitespace_only(self):
        self.assertFalse(is_merge_commit("   \n\t  "))

    def test_non_string_inputs_do_not_raise(self):
        for value in (0, 1, [], {}, ("Merge branch",), object(), 3.14, True):
            with self.subTest(value=value):
                self.assertFalse(is_merge_commit(value))

    def test_returns_a_real_bool_not_a_match_object(self):
        self.assertIs(is_merge_commit("Merge branch 'x'"), True)
        self.assertIs(is_merge_commit("nope"), False)


class CaseSensitivityTest(unittest.TestCase):
    """Case is the signal: git and GitHub always capitalize these phrases."""

    def test_lowercase_merge_branch_is_not_a_merge_commit(self):
        self.assertFalse(is_merge_commit("merge branch 'agent/x'"))

    def test_lowercase_merge_pull_request_is_not_a_merge_commit(self):
        self.assertFalse(is_merge_commit("merge pull request #42 from o/b"))

    def test_all_caps_is_not_a_merge_commit(self):
        self.assertFalse(is_merge_commit("MERGE BRANCH 'AGENT/X'"))

    def test_mixed_case_branch_word_is_not_a_merge_commit(self):
        self.assertFalse(is_merge_commit("Merge Branch 'agent/x'"))

    def test_prose_about_merging_is_not_a_merge_commit(self):
        self.assertFalse(is_merge_commit("chore: merge branch cleanup is overdue"))


class WhitespaceVariationTest(unittest.TestCase):
    """Real logs carry leading indentation, CRLF, and trailing newlines."""

    def test_leading_whitespace(self):
        self.assertTrue(is_merge_commit("    Merge branch 'agent/x'"))

    def test_trailing_newline(self):
        self.assertTrue(is_merge_commit("Merge branch 'agent/x'\n"))

    def test_crlf_line_endings(self):
        self.assertTrue(is_merge_commit("Merge pull request #7 from o/b\r\n\r\ntitle\r\n"))

    def test_tab_indented_body_line(self):
        self.assertTrue(is_merge_commit("wip\n\n\tMerge branch 'agent/x'\n"))

    def test_extra_internal_space_breaks_the_phrase(self):
        # "Merge  branch" (two spaces) is not what git emits; a literal phrase match is
        # correct here. Recorded so a future regex loosening is a deliberate choice.
        self.assertFalse(is_merge_commit("Merge  branch 'agent/x'"))


class SubtextTest(unittest.TestCase):
    """The phrase may appear anywhere in the message, not just as the whole subject."""

    def test_phrase_embedded_mid_sentence(self):
        self.assertTrue(is_merge_commit("This reverts commit that said Merge branch 'x'."))

    def test_phrase_inside_a_quoted_diff_line(self):
        msg = 'test: assert r.commit("Merge branch \'agent/x\' (auto-resolved)")'
        self.assertTrue(is_merge_commit(msg))

    def test_known_false_positive_is_documented_not_hidden(self):
        # A commit that only TALKS about merge messages matches. Substring matching cannot
        # distinguish these; parent count can, and callers with a repo should prefer it.
        self.assertTrue(is_merge_commit("fix: handle Merge branch messages in the parser"))

    def test_full_message_equal_to_the_phrase(self):
        self.assertTrue(is_merge_commit("Merge branch"))
        self.assertTrue(is_merge_commit("Merge pull request"))


class PurityTest(unittest.TestCase):
    """It is a pure function: no I/O, no state, same answer every time."""

    def test_repeated_calls_agree(self):
        for _ in range(3):
            self.assertTrue(is_merge_commit("Merge branch 'agent/x'"))
            self.assertFalse(is_merge_commit("feat: something"))

    def test_input_is_not_mutated(self):
        msg = "Merge branch 'agent/x'"
        is_merge_commit(msg)
        self.assertEqual(msg, "Merge branch 'agent/x'")


if __name__ == "__main__":
    unittest.main()
