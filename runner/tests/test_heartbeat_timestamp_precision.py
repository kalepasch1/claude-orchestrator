#!/usr/bin/env python3
"""A dead host must drop out of `live`, whatever width Postgres wrote its microseconds.

THE FAILURE THIS PINS (2026-08-30)
----------------------------------
integration_owner's docstring promises: "there is no way for a crashed owner to
wedge the fleet — if the owner stops heartbeating it drops out of `live`". It
could not keep that promise on Python < 3.11.

datetime.fromisoformat() accepts EXACTLY 3 or 6 fractional-second digits before
3.11. Postgres renders timestamptz with trailing zeros trimmed, so it emits 1-6
digits depending on the value. The newest runner_heartbeats row was

    {"hostname": "Mac.lan", "last_seen": "2026-08-27T18:52:05.72819+00:00"}

Five digits. It raised, _live_hosts() fell through to its deliberate fail-open
("treat as live rather than silently drop a host"), and a host dead for 75 hours
stayed live, won the election, and made every merge_train pass on the real host
refuse with "not the integration owner" — 532 passes, 0 branches considered.

The fail-open is correct and stays: refusing to integrate is safer than racing
another host onto shared refs. What was wrong is that a parser rejecting roughly
one row in ten kept reaching it.
"""
import datetime
import os
import sys

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RUNNER)

import common_utils  # noqa: E402
import integration_owner  # noqa: E402

# The exact row that wedged the fleet.
WEDGING_ROW = {"hostname": "Mac.lan",
               "code_sha": "9d72678599fd15f4798498302be0be1e4963cddf",
               "last_seen": "2026-08-27T18:52:05.72819+00:00"}

#: Fields of WEDGING_ROW["last_seen"], for asserting it parses to the right instant.
WEDGED_YEAR = 2026
WEDGED_SECOND = 5
#: 0.72819 seconds is 728190 microseconds — the value the old parser threw away.
WEDGED_MICROSECOND = 728190


def test_every_microsecond_width_postgres_can_emit_parses():
    """1 to 6 digits, plus none, plus Z. Postgres emits all of these."""
    for digits in range(1, 7):
        stamp = "2026-08-27T18:52:05." + ("7" * digits) + "+00:00"
        parsed = common_utils.parse_iso_timestamp(stamp)
        assert parsed is not None, "%d fractional digits failed to parse" % digits
        assert parsed.year == WEDGED_YEAR and parsed.second == WEDGED_SECOND
    assert common_utils.parse_iso_timestamp("2026-08-27T18:52:05+00:00") is not None
    assert common_utils.parse_iso_timestamp("2026-08-27T18:52:05.123Z") is not None


def test_five_digit_fraction_is_not_silently_dropped_to_none():
    """The specific width that raised. It must round-trip to a real instant."""
    parsed = common_utils.parse_iso_timestamp(WEDGING_ROW["last_seen"])
    assert parsed is not None
    assert parsed.microsecond == WEDGED_MICROSECOND, (
        "0.72819s is %dus, not %r" % (WEDGED_MICROSECOND, parsed.microsecond))


def test_garbage_still_returns_none():
    for junk in ("not a date", "", None, 17, "2026-13-45T99:99:99+00:00"):
        assert common_utils.parse_iso_timestamp(junk) is None


def test_a_host_dead_for_days_is_not_counted_live(monkeypatch):
    monkeypatch.setattr(integration_owner.db, "select",
                        lambda *a, **k: [dict(WEDGING_ROW)])
    assert integration_owner._live_hosts() == {}, (
        "a host last seen 2026-08-27 must not be live; the 5-digit fraction "
        "was reaching the fail-open path")


def test_a_host_that_really_is_alive_stays_live(monkeypatch):
    """Guard against 'fixing' staleness by dropping every host."""
    now = datetime.datetime.now(datetime.timezone.utc)
    fresh = dict(WEDGING_ROW)
    # Five fractional digits again — the width that used to raise — but recent.
    fresh["last_seen"] = now.strftime("%Y-%m-%dT%H:%M:%S.") + "72819+00:00"
    monkeypatch.setattr(integration_owner.db, "select",
                        lambda *a, **k: [fresh])
    assert integration_owner._live_hosts() == {
        "Mac.lan": WEDGING_ROW["code_sha"]}


def test_a_genuinely_unparseable_stamp_still_fails_open_to_live(monkeypatch):
    """The safety property itself, unchanged: never race another host on doubt."""
    row = dict(WEDGING_ROW, last_seen="whenever")
    monkeypatch.setattr(integration_owner.db, "select", lambda *a, **k: [row])
    assert integration_owner._live_hosts() == {"Mac.lan": WEDGING_ROW["code_sha"]}
