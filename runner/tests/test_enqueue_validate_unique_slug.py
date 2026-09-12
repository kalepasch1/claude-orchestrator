"""A slug already represented in the queue must not be queued again.

enqueue_task coalesces on intent_key, but its contract is explicitly NON-TERMINAL-only:
"a finished intent may legitimately recur". That is right for retries and decomposition
fan-out, and it is exactly why a slug sitting in DONE can be re-queued and an executor can
spend a whole run re-deriving an answer already recorded. validate_unique_slug is the
opt-in pre-queue check for that case.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from enqueue import (  # noqa: E402
    CLAIMED_STATES,
    normalize_slug,
    validate_unique_slug,
)


class TestClaimedStates:
    @pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "DONE"])
    def test_a_claimed_state_blocks_the_slug(self, state):
        assert validate_unique_slug("build-thing", {"build-thing": state}) is False

    def test_state_matching_is_case_insensitive(self):
        assert validate_unique_slug("build-thing", {"build-thing": "queued"}) is False

    @pytest.mark.parametrize("state", ["BLOCKED", "QUARANTINED", "SUPERSEDED", "FAILED"])
    def test_an_unclaimed_state_leaves_the_slug_available(self, state):
        assert validate_unique_slug("build-thing", {"build-thing": state}) is True

    def test_done_is_claimed_even_though_enqueue_task_treats_it_as_terminal(self):
        """The whole point: the coalescing rule deliberately allows this, and this does not."""
        from enqueue import TERMINAL_STATES
        assert "DONE" in TERMINAL_STATES
        assert "DONE" in CLAIMED_STATES
        assert validate_unique_slug("build-thing", {"build-thing": "DONE"}) is False

    def test_claimed_states_are_overridable(self):
        assert validate_unique_slug("x", {"x": "DONE"}, claimed_states={"QUEUED"}) is True


class TestSlugNormalisation:
    def test_a_fanout_slice_does_not_slip_past_its_base(self):
        assert validate_unique_slug("build-thing-slice-3", {"build-thing": "QUEUED"}) is False

    def test_a_queued_slice_blocks_the_base_slug(self):
        assert validate_unique_slug("build-thing", {"build-thing-slice-3": "RUNNING"}) is False

    def test_stacked_suffixes_still_collapse(self):
        assert validate_unique_slug(
            "build-thing-slice-3-slice-4", {"build-thing": "QUEUED"}) is False

    def test_a_genuinely_different_slug_is_unique(self):
        assert validate_unique_slug("other-thing", {"build-thing": "QUEUED"}) is True

    def test_matching_uses_the_same_normalisation_as_the_dedup_key(self):
        assert normalize_slug("build-thing-slice-3") == normalize_slug("build-thing")


class TestQueueStateShapes:
    def test_accepts_a_list_of_records(self):
        state = [{"slug": "build-thing", "state": "RUNNING"}]
        assert validate_unique_slug("build-thing", state) is False

    def test_accepts_bare_slugs_as_claims(self):
        assert validate_unique_slug("build-thing", ["build-thing"]) is False

    def test_a_record_without_a_state_is_treated_as_a_claim(self):
        assert validate_unique_slug("build-thing", [{"slug": "build-thing"}]) is False

    def test_a_record_for_another_slug_is_ignored(self):
        assert validate_unique_slug("build-thing", [{"slug": "other", "state": "RUNNING"}]) is True

    def test_an_empty_queue_leaves_everything_available(self):
        for state in ({}, [], None):
            assert validate_unique_slug("build-thing", state) is True


class TestFailOpen:
    """Bookkeeping failure must never silently swallow real work."""

    @pytest.mark.parametrize("state", [7, "a string", object()])
    def test_unusable_queue_state_reports_unique(self, state):
        assert validate_unique_slug("build-thing", state) is True

    def test_a_raising_iterable_reports_unique(self):
        def boom():
            raise RuntimeError("db unavailable")
            yield  # pragma: no cover

        assert validate_unique_slug("build-thing", boom()) is True

    def test_junk_entries_do_not_raise(self):
        assert validate_unique_slug("build-thing", [None, 7, {"nope": 1}]) is True


class TestEmptySlug:
    @pytest.mark.parametrize("slug", ["", "   ", None, 7])
    def test_an_unusable_slug_is_never_valid_to_queue(self, slug):
        assert validate_unique_slug(slug, {}) is False
