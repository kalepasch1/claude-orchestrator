"""Retry backoff must decorrelate concurrent clients.

The backoff was exactly `min(12, 2 ** attempt) + 0.1 * attempt`: deterministic,
so every client that failed at the same moment retried at the same moment. db.py
already records that failure mode in its own comments — on 2026-08-03 "the
arbitrage, batchmech and forecast jobs all crash-looped on 521/525 within the
same minute". With sixteen cowork executors plus the runner fleet against one
endpoint, a single 429 or 5xx blip re-synchronises the whole herd onto a
2s/4s/8s/12s drumbeat aimed at an origin that is already struggling.

Equal jitter keeps a growing floor (the property the curve was widened for)
while decorrelating the clients.
"""
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import db  # noqa: E402


def _base(attempt):
    """The original deterministic curve, kept here as the reference ceiling."""
    return min(12, 2 ** attempt) + (0.1 * attempt)


class TestEqualJitterBounds:
    @pytest.mark.parametrize("attempt", [0, 1, 2, 3, 4, 8])
    def test_delay_stays_within_half_the_curve_and_the_curve(self, attempt):
        for draw in (0.0, 0.25, 0.5, 0.75, 1.0):
            delay = db._retry_delay(attempt, _rand=lambda d=draw: d)
            assert _base(attempt) / 2 <= delay <= _base(attempt)

    def test_never_returns_zero(self, monkeypatch):
        """Full jitter can draw ~0 and hammer the origin; equal jitter cannot."""
        for attempt in range(6):
            assert db._retry_delay(attempt, _rand=lambda: 0.0) > 0

    def test_floor_still_grows_with_the_attempt(self):
        """The outage-riding property must survive the jitter."""
        floors = [db._retry_delay(a, _rand=lambda: 0.0) for a in range(5)]
        assert floors == sorted(floors)
        assert floors[-1] > floors[0]

    def test_cap_is_respected(self):
        assert db._retry_delay(30, _rand=lambda: 1.0) <= _base(30)


class TestDecorrelation:
    def test_two_clients_failing_together_do_not_retry_together(self):
        """The actual point: identical inputs must not produce identical delays."""
        delays = {db._retry_delay(3) for _ in range(200)}
        assert len(delays) > 1, "backoff is still deterministic; the herd stays in lockstep"

    def test_spread_covers_the_jitter_window(self):
        samples = [db._retry_delay(3) for _ in range(500)]
        assert max(samples) - min(samples) > _base(3) * 0.3


class TestOptOutAndFailSoft:
    def test_jitter_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(db, "ORCH_DB_RETRY_JITTER", False)
        assert db._retry_delay(3) == _base(3)

    def test_a_broken_rng_falls_back_to_the_curve(self):
        def boom():
            raise RuntimeError("no entropy")

        assert db._retry_delay(3, _rand=boom) == _base(3)

    @pytest.mark.parametrize("bad", [None, "three", object()])
    def test_a_bad_attempt_value_never_raises(self, bad):
        assert db._retry_delay(bad) > 0
