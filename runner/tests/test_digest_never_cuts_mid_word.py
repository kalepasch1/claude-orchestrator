"""The helper that exists to stop tail-truncation was tail-truncating.

Every caller in the fleet was migrated to `stderr_digest.digest()` so that
`stderr[-160:]` would stop cutting the cause off the front. digest() then ended
with `raw[-remaining:]` — a bare slice — so it cut mid-word anyway. Four live rows
from 2026-09-03, each read by a human or by an automated repair task:

    [gate:build] ... self-heal queued: nthropic-ai/sdk' imported from ...
    [gate:qa]    ... self-heal queued: e found in file /Users/.../check-patch-source.test.mjs
    [gate:qa]    ... self-heal queued:  duration_ms 30315.778334 ...

The first is missing both "Cannot find package" and the "@a" of the package name.
The second is missing "No test suit". Nobody can tell from those what went wrong,
which is the entire failure this module was written to end — and it is the shape
that sent a queued repair task after healthy git plumbing earlier the same day.
"""
import stderr_digest as sd


#: The real strings, from the live releases table.
DARWN_BUILD = (
    "ERROR  Cannot start nuxt:\n"
    "  Error: Cannot find package '@anthropic-ai/sdk' imported from "
    "/Users/kpasch/.orch-scratch/build-overlay-_a6mb2u2/.nuxt/prerender/chunks/nitro/nitro.mjs"
)
BARKS_QA = (
    "FAIL tests/check-patch-source.test.mjs\n"
    "Error: No test suite found in file "
    "/Users/kpasch/.orch-scratch/release-qa-overlay-0b9m9rln/tests/check-patch-source.test.mjs"
)


def test_the_darwn_row_now_starts_at_the_cause():
    out = sd.digest(DARWN_BUILD, 160)
    assert out.startswith("Error: Cannot find package '@anthropic-ai/sdk'")
    assert "nthropic-ai/sdk' imported" not in out[:20]


def test_the_sustainable_barks_row_now_starts_at_the_cause():
    out = sd.digest(BARKS_QA, 160)
    assert out.startswith("Error: No test suite found in file")


def test_a_digest_never_begins_mid_word():
    """The property, not the three examples."""
    for text in (DARWN_BUILD, BARKS_QA,
                 "x" * 40 + " some words here that run on and on and on and on",
                 "line one\nline two is quite long and keeps going for a while indeed"):
        for limit in (40, 80, 160, 200):
            out = sd.digest(text, limit)
            if not out or out.startswith("…"):
                continue
            assert text.startswith(out[:8]) or out[0] not in "abcdefghijklmnopqrstuvwxyz" \
                or f" {out[:8]}" in text or f"\n{out[:8]}" in text, \
                f"digest({limit}) began mid-word: {out[:40]!r}"


def test_a_token_longer_than_the_budget_is_marked_not_silently_cut():
    """An unbreakable 300-char token must say the front is missing."""
    out = sd.digest("z" * 400, 60)
    assert out.startswith("…"), out[:20]
    assert len(out) <= 61


def test_short_text_is_returned_whole():
    assert sd.digest("all of it", 160) == "all of it"


def test_empty_input_is_still_empty():
    assert sd.digest(None) == "" and sd.digest("") == ""


def test_the_limit_is_still_respected():
    for limit in (20, 60, 160):
        assert len(sd.digest(DARWN_BUILD, limit)) <= limit + 1   # +1 for the ellipsis


def test_the_diagnostic_line_still_comes_first():
    """The behaviour this module was built for must survive the boundary fix."""
    text = "noise\n" * 50 + "Error: the actual cause\n" + "more noise\n" * 50
    assert "Error: the actual cause" in sd.digest(text, 160)


def test_digest_still_never_raises():
    class Nasty:
        def __str__(self):
            raise ValueError("no")

    assert isinstance(sd.digest(Nasty()), str)


def test_the_boundary_helper_prefers_a_line_then_a_space():
    assert sd._tail_at_a_boundary("aaa\nbbb ccc", 8) == "bbb ccc"
    assert sd._tail_at_a_boundary("aaaaa bbb ccc", 8) == "bbb ccc"
    assert sd._tail_at_a_boundary("short", 99) == "short"
