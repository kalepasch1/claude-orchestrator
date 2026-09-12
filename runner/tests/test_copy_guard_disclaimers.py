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
])
def test_a_regulatory_playbook_is_still_blocked(copy):
    assert _rule(LEGAL).search(copy), "the rule went permissive: %r" % copy


# ── the regulatory disclaimers: reported, not blocking ───────────────────────
#
# Operator decision 2026-09-02, after the attorney-advertising disclaimer failed nine
# apparently-law releases: "not custody", "not money transmission", "not securities"
# and "not a broker-dealer" are the same shape. They say what the product is NOT, to
# protect the reader, which is the opposite of disclosing a playbook. They no longer
# block; they file a coordination task naming the page instead.

@pytest.mark.parametrize("copy", [
    "the service is not custody",
    "this is not money transmission",
    "these are not securities",
    "we are not a broker-dealer",
    "Nothing here is investment advice.",
])
def test_a_regulatory_disclaimer_no_longer_blocks(copy):
    for name, pattern, _message in public_copy_guard.RULES:
        assert not pattern.search(copy), "%s still blocks a disclaimer: %r" % (name, copy)


@pytest.mark.parametrize("copy", [
    "the service is not custody",
    "this is not money transmission",
    "these are not securities",
    "we are not a broker-dealer",
])
def test_a_regulatory_disclaimer_is_still_reported(copy):
    """Unblocking is not the same as ignoring. The operator asked to be told."""
    assert any(p.search(copy) for _n, p, _m in public_copy_guard.DISCLAIMER_RULES), (
        "a disclaimer was unblocked AND silenced: %r" % copy)


@pytest.mark.parametrize("copy", [
    "avoids SEC registration by design",
    "our regulatory arbitrage playbook",
    "Attorney advertising. Informational only, not legal advice.",
    "Privacy-preserving and compliance-aware.",
])
def test_the_advisory_rule_does_not_fire_on_everything_else(copy):
    assert not any(p.search(copy) for _n, p, _m in public_copy_guard.DISCLAIMER_RULES)


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


# ── the alert: one row per page-set per day, never a metronome ────────────────

class _AlertDB:
    def __init__(self, existing=None, boom=False):
        self.existing = existing or []
        self.boom = boom
        self.inserts = []

    def select(self, table, params=None):
        if self.boom:
            raise RuntimeError("control plane down")
        return list(self.existing)

    def insert(self, table, row, **kw):
        self.inserts.append((table, row))
        return row


ADVISORY = [{"file": "app/pages/pricing.vue", "line": 12, "rule": "regulatory_disclaimer",
             "excerpt": "this is not money transmission", "guidance": "..."}]


def test_the_alert_names_the_page(monkeypatch):
    db = _AlertDB()
    monkeypatch.setitem(sys.modules, "db", db)
    assert public_copy_guard._alert_disclaimers("kalepasch-com", ADVISORY) is True
    table, row = db.inserts[0]
    assert table == "coordination_tasks"
    assert row["task_type"] == "public_copy_disclaimer"
    assert "app/pages/pricing.vue:12" in row["payload"]
    assert "kalepasch-com" in row["payload"]


def test_the_same_pages_are_not_alerted_twice(monkeypatch):
    db = _AlertDB()
    monkeypatch.setitem(sys.modules, "db", db)
    public_copy_guard._alert_disclaimers("p", ADVISORY)
    sig = [r for _t, r in db.inserts][0]["payload"]
    db2 = _AlertDB(existing=[{"id": "1", "payload": sig}])
    monkeypatch.setitem(sys.modules, "db", db2)
    assert public_copy_guard._alert_disclaimers("p", ADVISORY) is False
    assert db2.inserts == []


def test_a_different_page_gets_its_own_alert(monkeypatch):
    db = _AlertDB()
    monkeypatch.setitem(sys.modules, "db", db)
    public_copy_guard._alert_disclaimers("p", ADVISORY)
    first = db.inserts[0][1]["payload"]
    other = [dict(ADVISORY[0], file="app/pages/terms.vue", line=99)]
    db2 = _AlertDB(existing=[{"id": "1", "payload": first}])
    monkeypatch.setitem(sys.modules, "db", db2)
    assert public_copy_guard._alert_disclaimers("p", other) is True


def test_an_unreadable_dedupe_check_still_records_the_alert(monkeypatch):
    """Fail-open on the DEDUPE read: an alert nobody can look up is worse than a
    duplicate one. Same reasoning as done_to_merged's rejection recorder."""
    db = _AlertDB(boom=True)
    monkeypatch.setitem(sys.modules, "db", db)
    assert public_copy_guard._alert_disclaimers("p", ADVISORY) is True
    assert db.inserts, "the alert was dropped because the dedupe read failed"


def test_a_fully_unreachable_control_plane_never_breaks_the_gate(monkeypatch):
    """The guarantee that matters: reporting must never be why a release fails."""
    class _Dead:
        def select(self, *a, **k):
            raise RuntimeError("down")

        def insert(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setitem(sys.modules, "db", _Dead())
    assert public_copy_guard._alert_disclaimers("p", ADVISORY) is False


def test_scan_lines_can_be_pointed_at_either_rule_set():
    line = [(1, '<p>this is not money transmission</p>')]
    path = "app/pages/pricing.vue"
    assert public_copy_guard.scan_lines(path, line) == []
    advisory = public_copy_guard.scan_lines(path, line,
                                            rules=public_copy_guard.DISCLAIMER_RULES)
    assert advisory and advisory[0]["rule"] == "regulatory_disclaimer"
