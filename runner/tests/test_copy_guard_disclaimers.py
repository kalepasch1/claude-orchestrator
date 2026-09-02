"""A bar-required disclaimer is not a regulatory playbook.

2026-09-02: nine apparently-law releases failed on this, and the gate quoted the line
it objected to:

    [gate:copy] public-copy disclosure gate red — self-heal queued:
    - app/pages/for/ai-data.vue:21 [legal_strategy]: Informational only not legal advice.

The line in the repo reads, in full:

    Attorney advertising. Informational only, not legal advice. No attorney-client
    relationship is formed by using this site or by submitting a form.

That is the attorney-advertising disclaimer a law-adjacent site is REQUIRED to display,
and it appears in at least eight places across that site -- index.vue, the /learn/videos
pages, LegalSpendModel.vue, site.ts and more. The guard was blocking releases for
publishing text the bar obliges them to publish.

The distinction the rule is actually for: a STRATEGY says how the company avoids a
regulator; a DISCLAIMER says what the product is not, to protect the reader. The
`avoid(s|ing) ... legal advice` branch still catches the first. Only the disclaimer
phrasing was removed, and the tests below pin both halves so the rule cannot quietly
become permissive.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import public_copy_guard  # noqa: E402


def _rule(name):
    for rule_name, pattern, _message in public_copy_guard.RULES:
        if rule_name == name:
            return pattern
    raise AssertionError("rule %r is gone" % name)


LEGAL = "legal_strategy"


# ── disclaimers: must NOT trip the gate ──────────────────────────────────────

@pytest.mark.parametrize("copy", [
    # verbatim from apparently-law, the line that failed nine releases
    "Attorney advertising. Informational only, not legal advice. No attorney-client "
    "relationship is formed by using this site or by submitting a form.",
    "Informational only, not legal advice.",
    "Educational — not legal advice.",
    "This site is informational and is not legal advice. Using it does not create an "
    "attorney-client relationship.",
    "It is not a quote, not a saving that has been measured, and not legal advice.",
])
def test_a_required_disclaimer_passes(copy):
    assert not _rule(LEGAL).search(copy), (
        "the gate would block a mandatory attorney-advertising disclaimer")


# ── strategy disclosure: must STILL trip the gate ────────────────────────────

@pytest.mark.parametrize("copy", [
    "We structure the product to avoid legal advice liability entirely.",
    "avoids SEC registration by design",
    "avoiding money transmission licensing",
    "our regulatory arbitrage playbook",
    "our legal strategy is to stay under the UPL threshold",
    "the privilege guard keeps work-product strategy out of discovery",
    "avoids broker-dealer registration",
    "the service is not custody",              # left in deliberately; see the rule
    "this is not money transmission",
    "these are not securities",
])
def test_a_regulatory_playbook_is_still_blocked(copy):
    assert _rule(LEGAL).search(copy), "the rule went permissive: %r" % copy


# ── the other rules are untouched ────────────────────────────────────────────

def test_the_other_three_rules_still_exist():
    names = [name for name, _p, _m in public_copy_guard.RULES]
    assert names == ["proprietary_mechanism", "legal_strategy",
                     "vendor_ip_partitioning", "specific_vendor_routing"]


@pytest.mark.parametrize("copy,rule", [
    ("our common brain routes work", "proprietary_mechanism"),
    ("no single model sees the full IP", "vendor_ip_partitioning"),
    ("we route to Claude based on cost", "specific_vendor_routing"),
])
def test_the_neighbouring_rules_still_fire(copy, rule):
    assert _rule(rule).search(copy)


def test_ordinary_marketing_copy_passes_every_rule():
    copy = ("Privacy-preserving and compliance-aware. Built for teams who need "
            "answers fast, reviewed by licensed attorneys.")
    for name, pattern, _message in public_copy_guard.RULES:
        assert not pattern.search(copy), "%s flagged ordinary marketing copy" % name
