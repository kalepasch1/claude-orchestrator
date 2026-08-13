"""Deterministic fixture tests for approved-source regulatory ingestion.

The four cases the brief names — first observation, meaningful change, unchanged
content, malformed source responses — plus the refusals, which are the part that
actually keeps us out of trouble.

No network. Every transport is a dict lookup, so a failure here is a logic failure
rather than a flaky one.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from regulation_ingestion import (  # noqa: E402
    ApprovedFetchAdapter,
    ApprovedSource,
    ContentVersionStore,
    MalformedSourceResponse,
    RegulationIngestion,
    RobotsDisallowed,
    SourceNotApproved,
    SourceRegistry,
    TermsForbidAutomatedAccess,
    extract_change,
    normalise_content,
    robots_disallows,
    validate_response,
)

LONG = "The Commission hereby amends section 4 of the rule concerning entries. " * 40


def approved(**over):
    base = dict(
        source_id="mgcb-rules",
        url="https://example.invalid/mgcb/rules",
        regulator_id="mgcb",
        jurisdiction="US-MI",
        terms_allow_automated_access=True,
        terms_reviewed_at="2026-08-01T00:00:00Z",
        terms_reviewed_by="counsel",
    )
    base.update(over)
    return ApprovedSource(**base)


def build(pages, robots=None, sources=None, publish=None):
    registry = SourceRegistry(sources or [approved()])
    adapter = ApprovedFetchAdapter(
        registry,
        transport=lambda url: pages[url],
        robots_transport=(lambda url: robots) if robots is not None else None,
    )
    ticks = iter(f"2026-08-12T00:{i:02d}:00+00:00" for i in range(60))
    return RegulationIngestion(
        registry, adapter, ContentVersionStore(), publish=publish, clock=lambda: next(ticks)
    )


# --------------------------------------------------------------------------- #
# Approval gates
# --------------------------------------------------------------------------- #


def test_unapproved_source_is_never_fetched():
    fetched = []
    registry = SourceRegistry([approved()])
    adapter = ApprovedFetchAdapter(
        registry, transport=lambda url: fetched.append(url) or LONG
    )
    with pytest.raises(SourceNotApproved):
        adapter("https://example.invalid/somewhere-else")
    # The point is not that it raised. It is that nothing was fetched.
    assert fetched == []


def test_terms_gate_is_checked_before_any_traffic():
    fetched = []
    robots_hits = []
    registry = SourceRegistry([approved(terms_allow_automated_access=False)])
    adapter = ApprovedFetchAdapter(
        registry,
        transport=lambda url: fetched.append(url) or LONG,
        robots_transport=lambda url: robots_hits.append(url) or "",
    )
    with pytest.raises(TermsForbidAutomatedAccess):
        adapter("https://example.invalid/mgcb/rules")
    # A forbidden source generates NO traffic at all — not even a robots.txt read.
    assert fetched == []
    assert robots_hits == []


def test_unreviewed_terms_default_to_forbidden():
    # The failure guarded against is a source becoming fetchable because nobody
    # filled a field in.
    source = ApprovedSource(
        source_id="s", url="https://example.invalid/s", regulator_id="r", jurisdiction="j"
    )
    assert source.terms_allow_automated_access is False


def test_robots_disallow_is_fatal_not_advisory():
    registry = SourceRegistry([approved()])
    adapter = ApprovedFetchAdapter(
        registry,
        transport=lambda url: LONG,
        robots_transport=lambda url: "User-agent: *\nDisallow: /mgcb/",
    )
    with pytest.raises(RobotsDisallowed):
        adapter("https://example.invalid/mgcb/rules")


def test_robots_allows_when_path_not_covered():
    registry = SourceRegistry([approved()])
    adapter = ApprovedFetchAdapter(
        registry,
        transport=lambda url: LONG,
        robots_transport=lambda url: "User-agent: *\nDisallow: /private/",
    )
    assert adapter("https://example.invalid/mgcb/rules") == LONG


def test_unparseable_robots_refuses_rather_than_assuming_permission():
    # Treating a malformed policy as permission gets the answer wrong in the one
    # direction that matters.
    assert robots_disallows("!!! not a policy !!!", "https://x.invalid/a") == "/"
    assert robots_disallows(None, "https://x.invalid/a") == "/"


def test_empty_robots_allows():
    assert robots_disallows("", "https://x.invalid/a") is None


def test_bare_disallow_allows_everything():
    assert robots_disallows("User-agent: *\nDisallow:", "https://x.invalid/a") is None


def test_refusals_are_distinct_exception_types():
    # So a caller cannot collapse them into one "fetch failed" branch and retry
    # past the reason.
    assert not issubclass(SourceNotApproved, TermsForbidAutomatedAccess)
    assert not issubclass(RobotsDisallowed, SourceNotApproved)


# --------------------------------------------------------------------------- #
# Case 1 — first observation
# --------------------------------------------------------------------------- #


def test_first_observation_is_not_a_change():
    ingestion = build({"https://example.invalid/mgcb/rules": LONG})
    result = ingestion.ingest(["mgcb-rules"])

    assert len(result.changes) == 1
    change = result.changes[0]
    assert change.kind == "first_observation"
    # One data point cannot be a difference.
    assert change.confidence == 0.0
    assert change.previous_hash is None
    assert "cannot be a difference" in change.reason


def test_first_observation_records_full_provenance():
    ingestion = build({"https://example.invalid/mgcb/rules": LONG})
    prov = ingestion.ingest(["mgcb-rules"]).changes[0].provenance
    for key in ("source_id", "url", "regulator_id", "jurisdiction", "fetched_at",
                "content_hash", "terms_reviewed_at", "terms_reviewed_by"):
        assert prov[key] is not None, key


# --------------------------------------------------------------------------- #
# Case 2 — meaningful change
# --------------------------------------------------------------------------- #


def test_meaningful_change_is_detected_with_high_confidence():
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages)
    ingestion.ingest(["mgcb-rules"])

    pages["https://example.invalid/mgcb/rules"] = LONG + (
        " Section 9 is added: operators shall verify age before first play. " * 20
    )
    change = ingestion.ingest(["mgcb-rules"]).changes[0]

    assert change.kind == "changed"
    assert change.confidence >= 0.9
    assert change.delta_chars > 0
    assert change.previous_hash != change.current_hash


def test_a_tiny_delta_on_a_large_document_gets_LOW_confidence():
    # More likely residual noise the normaliser missed than a substantive
    # amendment — and saying so is more useful than a flat "changed: true".
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages)
    ingestion.ingest(["mgcb-rules"])

    pages["https://example.invalid/mgcb/rules"] = LONG + "x"
    change = ingestion.ingest(["mgcb-rules"]).changes[0]

    assert change.kind == "changed"
    assert change.confidence < 0.5
    assert "residual noise" in change.reason


def test_same_length_substitution_is_real_but_smallest_kind_of_real():
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages)
    ingestion.ingest(["mgcb-rules"])

    pages["https://example.invalid/mgcb/rules"] = LONG.replace("section 4", "section 5")
    change = ingestion.ingest(["mgcb-rules"]).changes[0]

    assert change.kind == "changed"
    assert change.delta_chars == 0
    assert "substitution" in change.reason


def test_change_appends_a_version_and_history_is_append_only():
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages)
    ingestion.ingest(["mgcb-rules"])
    pages["https://example.invalid/mgcb/rules"] = LONG + " new material. " * 30
    ingestion.ingest(["mgcb-rules"])

    history = ingestion.store.history("mgcb-rules")
    assert len(history) == 2
    assert history[0].content_hash != history[1].content_hash


# --------------------------------------------------------------------------- #
# Case 3 — unchanged content
# --------------------------------------------------------------------------- #


def test_unchanged_content_is_reported_and_stores_no_new_version():
    ingestion = build({"https://example.invalid/mgcb/rules": LONG})
    ingestion.ingest(["mgcb-rules"])
    change = ingestion.ingest(["mgcb-rules"]).changes[0]

    assert change.kind == "unchanged"
    assert change.confidence == 1.0
    # Appending an identical version on every poll makes the history a poll log
    # rather than a change history.
    assert ingestion.store.version_count("mgcb-rules") == 1


def test_timestamp_churn_does_not_register_as_a_change():
    # A change detector that fires on every poll is an alarm nobody reads.
    pages = {"https://example.invalid/mgcb/rules": f"{LONG} Retrieved 2026-08-12T00:00:00Z"}
    ingestion = build(pages)
    ingestion.ingest(["mgcb-rules"])

    pages["https://example.invalid/mgcb/rules"] = f"{LONG} Retrieved 2026-08-13T09:31:07Z"
    assert ingestion.ingest(["mgcb-rules"]).changes[0].kind == "unchanged"


def test_whitespace_and_comment_churn_is_normalised_away():
    a = normalise_content("The   rule\n\nstates  X. <!-- build 1 -->")
    b = normalise_content("The rule states X. <!-- build 2 -->")
    assert a == b


# --------------------------------------------------------------------------- #
# Case 4 — malformed source responses
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [None, b"bytes not str", "", "   ", "404 Not Found", "tiny"],
)
def test_malformed_responses_are_refused(payload):
    with pytest.raises(MalformedSourceResponse):
        validate_response("s", payload)


def test_a_malformed_response_stores_nothing_and_is_reported():
    # An outage must not record a change on the way in and another on recovery.
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages)
    ingestion.ingest(["mgcb-rules"])

    pages["https://example.invalid/mgcb/rules"] = "503 Service Unavailable"
    result = ingestion.ingest(["mgcb-rules"])

    assert result.changes == []
    assert result.refused[0]["reason"] == "MalformedSourceResponse"
    assert ingestion.store.version_count("mgcb-rules") == 1

    # And on recovery, the unchanged content is still unchanged.
    pages["https://example.invalid/mgcb/rules"] = LONG
    assert ingestion.ingest(["mgcb-rules"]).changes[0].kind == "unchanged"


def test_unknown_source_id_is_refused_not_crashed():
    ingestion = build({"https://example.invalid/mgcb/rules": LONG})
    result = ingestion.ingest(["no-such-source"])
    assert result.changes == []
    assert result.refused[0]["reason"] == "not_approved"


# --------------------------------------------------------------------------- #
# Event publication
# --------------------------------------------------------------------------- #


def test_publishes_regulation_ingested_with_provenance():
    published = []
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages, publish=lambda kind, payload: published.append((kind, payload)))
    ingestion.ingest(["mgcb-rules"])

    assert published[0][0] == "regulation.ingested"
    payload = published[0][1]
    assert payload["regulator_id"] == "mgcb"
    assert payload["provenance"]["url"].startswith("https://")


def test_unchanged_content_publishes_nothing():
    published = []
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages, publish=lambda kind, payload: published.append(kind))
    ingestion.ingest(["mgcb-rules"])
    ingestion.ingest(["mgcb-rules"])
    assert published == ["regulation.ingested"]


def test_low_confidence_change_is_recorded_but_not_published():
    # A channel that emits every 0.35-confidence flicker is a channel operators mute.
    published = []
    pages = {"https://example.invalid/mgcb/rules": LONG}
    ingestion = build(pages, publish=lambda kind, payload: published.append(kind))
    ingestion.ingest(["mgcb-rules"])
    published.clear()

    pages["https://example.invalid/mgcb/rules"] = LONG + "x"
    result = ingestion.ingest(["mgcb-rules"])

    assert result.changes[0].kind == "changed"
    assert published == []


def test_scanner_still_refuses_to_run_without_an_adapter():
    # The scanner staying adapter-only is what prevents it ever reaching the
    # network on its own.
    from regulation_scanner import PredictiveRegulationScanner

    with pytest.raises(RuntimeError):
        PredictiveRegulationScanner().scan(["https://example.invalid/x"])


def test_extract_change_is_pure_and_deterministic():
    source = approved()
    store = ContentVersionStore()
    from regulation_ingestion import ContentVersion

    v1 = ContentVersion("mgcb-rules", "a" * 64, "text one", "2026-08-12T00:00:00Z", 8)
    v2 = ContentVersion("mgcb-rules", "b" * 64, "text two", "2026-08-12T00:01:00Z", 8)
    store.append(v1)

    first = extract_change(source, v1, v2)
    second = extract_change(source, v1, v2)
    assert first == second
