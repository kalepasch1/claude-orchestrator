"""A provider's billing notice must never be mistaken for model output.

Providers do not raise when they throttle or run out of budget — they return
prose down the same channel as a real completion. It has been mistaken for
content twice: once into CLAUDE.md and regression memory (2026-07-08), and
once as the entire "drift found:" evidence of a spec-reconcile task.

Both fixes were written locally, so three modules ended up carrying their own
copy of the vocabulary and the copies drifted. This suite pins the shared
module and, more importantly, pins that the three consumers agree: a phrase any
one of them knows must now be known to all of them.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provider_banner as pb


EXHAUSTION_BANNERS = [
    "You've hit your weekly limit · resets Jul 29 at 5am (America/Chicago)",
    "You've hit your monthly limit · raise it at claude.ai",
    "5-hour limit reached ∙ resets 3pm",
    "Usage limit reached",
    "You are out of credits",
    "insufficient_quota",
    "Approaching your spend limit",
]

RATE_BANNERS = [
    "We're temporarily limiting requests, please try again",
    "429 Too Many Requests",
    "Rate limit exceeded",
    "Overloaded",
]

REAL_CONTENT = [
    "- Use camelCase for variables and PascalCase for types\n- Import order: node, third-party, aliases",
    "The build failed because runner/foo.py imports a module that does not exist.",
    "def main(): return 0",
    "",
    None,
]


@pytest.mark.parametrize("text", EXHAUSTION_BANNERS)
def test_exhaustion_banners_are_classified_as_exhausted(text):
    assert pb.classify(text) == "exhausted", text


@pytest.mark.parametrize("text", RATE_BANNERS)
def test_rate_banners_are_classified_as_rate_limited(text):
    assert pb.classify(text) == "rate_limited", text


@pytest.mark.parametrize("text", EXHAUSTION_BANNERS + RATE_BANNERS)
def test_every_banner_is_recognised_as_a_banner(text):
    assert pb.is_banner(text)


@pytest.mark.parametrize("text", REAL_CONTENT)
def test_real_content_is_not_a_banner(text):
    assert not pb.is_banner(text), text
    assert pb.classify(text) is None


def test_exhaustion_wins_over_rate_limit_when_both_appear():
    """Backing off does not fix an empty account — the remedy differs."""
    both = "429: you have hit your weekly limit, resets Jul 29"
    assert pb.classify(both) == "exhausted"


def test_provider_errors_are_their_own_category():
    assert pb.classify("HTTP 503 Service Unavailable") == "provider_error"


def test_reason_names_the_phrase_not_the_regex():
    """An operator can act on a phrase; a regex source tells them nothing."""
    why = pb.reason("You've hit your weekly limit · resets Jul 29 at 5am")
    assert why.startswith("exhausted: ")
    assert "\\b" not in why and "re.I" not in why


def test_reason_is_none_for_real_content():
    assert pb.reason("- Prefer the smallest diff\n- Reuse existing helpers") is None


@pytest.mark.parametrize("junk", [None, 123, b"bytes", object(), ["list"]])
def test_nothing_raises_on_junk_input(junk):
    """These run on the error path, where a second failure is the expensive one."""
    assert pb.classify(junk) is None
    assert pb.is_banner(junk) is False
    assert pb.reason(junk) is None


# --- the three consumers must not drift apart again ------------------------

@pytest.mark.parametrize("text", EXHAUSTION_BANNERS + RATE_BANNERS)
def test_root_cause_classifies_every_banner_the_runner_knows(text):
    """root_cause used to know only 'weekly limit' out of this whole list."""
    import root_cause

    categories = [name for name, _conf in root_cause.classify_failure(text)]
    assert "rate_limit" in categories or "exhausted" in categories, (
        "root_cause returned %r for a banner the runner handles" % categories)


@pytest.mark.parametrize("text", EXHAUSTION_BANNERS + RATE_BANNERS)
def test_the_learning_quality_gate_rejects_every_banner(text):
    """Text like this reached CLAUDE.md on 2026-07-08."""
    import learn_from_merges

    accepted, why = learn_from_merges.quality_gate(text)
    assert not accepted, "quality_gate accepted a provider banner: %r" % why


def test_runner_rate_and_exhaust_tuples_come_from_the_shared_module():
    """runner.py held the richest copy; it must now be reading the shared one.

    Asserted against the source rather than by importing runner.py, which
    acquires the singleton lock at import time and would fight a live runner.
    """
    source = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "runner.py")).read()

    assert "RATE = provider_banner.RATE_SIGNALS" in source
    assert "EXHAUST = provider_banner.EXHAUST_SIGNALS" in source
    assert 'RATE = ("temporarily limiting"' not in source, "local copy came back"


def test_the_phrases_runner_already_handled_are_all_still_present():
    """Regression guard for the consolidation itself: nothing was dropped."""
    for phrase in ("usage limit", "out of credits", "insufficient_quota", "quota",
                   "weekly limit", "hit your weekly", "limit · resets",
                   "limit - resets", "reached your usage", "usage limit reached",
                   "upgrade to increase", "5-hour limit", "hour limit reached",
                   "session limit", "limit reached ∙ resets", "spend limit",
                   "monthly spend", "monthly limit", "hit your monthly",
                   "limit · raise it", "raise it at claude.ai"):
        assert phrase in pb.EXHAUST_SIGNALS, phrase
    for phrase in ("temporarily limiting", "rate limit", "429", "overloaded",
                   "too many requests"):
        assert phrase in pb.RATE_SIGNALS, phrase


def test_exhaustion_gets_its_own_recommendation_not_the_throttling_one():
    """Reducing concurrency does not refill an empty account."""
    import root_cause

    banner = "You've hit your weekly limit · resets Jul 29 at 5am"
    report = root_cause.analyze_batch(
        [{"note": banner, "project_name": "beethoven"} for _ in range(4)])

    advice = " ".join(report["recommendations"])
    assert "rotate to another account" in advice
    assert "will not help" in advice
