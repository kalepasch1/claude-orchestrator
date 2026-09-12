"""A failure record has to say what failed.

_run_tests returns up to 12,000 characters -- the last 6,000 of stdout plus the last
6,000 of stderr -- and the TESTFAIL path took tail[:200], the FRONT of that window, for
the task note, the log line and (through agentic_repair) the repair agent's evidence.
Every runner in this fleet prints its failure summary at the END, so what came out was an
arbitrary slice of whatever was mid-flight.

Measured 2026-09-02 over 385 TESTFAIL records in one merge-train log: 290 (75%) carried
no failure marker of any kind, and 61 of those opened with PASSING test output. What a
repair agent was handed as the reason for a failure:

    [smarter]    "ByName: string; workspaceId: string; createdAt: string; lastActi"
    [beethoven]  "capability across products (0.610084ms"
    [tomorrow]   "ests__/tracing.test.ts > tracing.withSpan > clears currentSpan af"
"""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import failure_excerpt  # noqa: E402


VITEST = (
    " ✓ server/utils/otc/d8Lifecycle.test.ts (19 tests) 8ms\n"
    " ✓ server/api/pricing/__tests__/pricing.test.ts (12 tests) 11ms\n"
    " ✓ server/utils/otc/federation/__tests__/federation.test.ts (5 tests) 17ms\n"
    " ❯ server/utils/__tests__/tracing.test.ts (6 tests | 1 failed) 22ms\n"
    "   × tracing.withSpan > clears currentSpan after returning\n"
    "     AssertionError: expected undefined to be 'root-span'\n"
    "Test Files  1 failed | 42 passed (43)\n"
)

TSC = (
    "src/a.ts:1:1 - checked\nsrc/b.ts:2:2 - checked\n"
    "src/pricing.ts:88:14 - error TS2345: Argument of type 'string' is not "
    "assignable to parameter of type 'number'.\n"
    "Found 1 error in src/pricing.ts:88\n"
)

NPM = ('npm error Missing script: "test"\nnpm error\n'
       'npm error To see a list of scripts, run:\nnpm error   npm run\n')

PASSING_PREFIX = "\n".join(" ✓ suite/%03d.test.ts (9 tests) 4ms" % n for n in range(200))


def test_a_vitest_failure_names_the_failing_assertion():
    out = failure_excerpt.excerpt(VITEST, 200)
    assert "AssertionError" in out
    assert "expected undefined to be 'root-span'" in out


def test_the_old_head_selection_would_have_missed_it():
    """The regression, stated as a test."""
    assert "AssertionError" not in VITEST[:60]
    assert "✓" in VITEST[:60]


def test_passing_lines_are_not_selected():
    out = failure_excerpt.excerpt(VITEST, 200)
    assert "✓ server/utils/otc/d8Lifecycle" not in out


def test_a_long_passing_prefix_does_not_crowd_out_the_failure():
    """The live shape: thousands of green lines, one red one at the end."""
    out = failure_excerpt.excerpt(PASSING_PREFIX + "\n" + VITEST, 200)
    assert "AssertionError" in out


def test_a_typescript_error_is_selected_with_its_file_and_line():
    out = failure_excerpt.excerpt(TSC, 200)
    assert "error TS2345" in out
    assert "src/pricing.ts:88" in out


def test_an_npm_failure_is_selected():
    out = failure_excerpt.excerpt(NPM, 200)
    assert 'Missing script: "test"' in out


def test_a_missing_binary_is_selected():
    out = failure_excerpt.excerpt("some noise\nbash: npm: command not found\n", 200)
    assert "command not found" in out


def test_a_timeout_is_selected():
    out = failure_excerpt.excerpt("running\nrunning\ntests timed out after 900s\n", 200)
    assert "timed out" in out


def test_a_python_traceback_is_selected():
    out = failure_excerpt.excerpt(
        "collecting ...\ncollected 40 items\nTraceback (most recent call last):\n"
        "  File 'x.py', line 3\nValueError: bad\n", 200)
    assert "Traceback" in out or "ValueError" in out


def test_the_limit_is_respected():
    for limit in (40, 80, 160, 240):
        assert len(failure_excerpt.excerpt(PASSING_PREFIX + VITEST, limit)) <= limit


def test_a_zero_or_negative_limit_returns_empty():
    assert failure_excerpt.excerpt(VITEST, 0) == ""
    assert failure_excerpt.excerpt(VITEST, -5) == ""


def test_empty_output_returns_empty():
    for value in ("", "   \n\n", None):
        assert failure_excerpt.excerpt(value, 200) == ""


def test_output_with_no_markers_falls_back_to_the_TAIL_not_the_head():
    text = "\n".join("line %03d" % n for n in range(500))
    out = failure_excerpt.excerpt(text, 120)
    assert "line 499" in out
    assert "line 000" not in out


def test_the_fallback_never_returns_empty():
    assert failure_excerpt.excerpt("aaaa", 200) == "aaaa"
    assert failure_excerpt.excerpt("x" * 5000, 100) != ""


def test_the_excerpt_never_starts_mid_word_on_the_fallback():
    text = "\n".join("a rather long line number %03d here" % n for n in range(300))
    out = failure_excerpt.excerpt(text, 100)
    assert out.lstrip().startswith("a rather") or out.startswith("a rather")


def test_failure_lines_skips_blank_and_passing_lines():
    lines = failure_excerpt.failure_lines(VITEST)
    assert lines
    assert not any(line.strip().startswith("✓") for line in lines)


def test_a_passing_test_whose_NAME_contains_error_is_not_selected():
    """"error" inside a green test's name is not a diagnosis."""
    text = " ✓ handles error responses gracefully (3 tests) 2ms\n"
    assert failure_excerpt.failure_lines(text) == []


@pytest.mark.parametrize("marker", [
    "FAIL src/x.test.ts", "1 failing", "AssertionError: nope", "Error: boom",
    "error TS1005: ';' expected", "Cannot find module 'x'", "ENOENT: no such file",
    "bash: npx: command not found", "Tests  3 failed", "exit code 1",
])
def test_common_failure_shapes_are_all_recognised(marker):
    assert failure_excerpt.failure_lines("noise\n%s\n" % marker), marker


def test_merge_train_uses_it_at_the_testfail_site():
    """Structural: the TESTFAIL path must not go back to slicing the head."""
    import merge_train
    src = open(merge_train.__file__.replace(".pyc", ".py")).read()
    block = src[src.index('_task_patch(task, {"state": "TESTFAIL"'):][:400]
    assert "tail[:200]" not in block, block
    assert "_why" in block, block


def test_merge_train_imports_it():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "merge_train.py")).read()
    assert re.search(r"^import failure_excerpt", src, re.M)


# ── ranking: name WHICH test failed, not just how many ───────────────────────────────
#
# The first live records this produced (2026-09-02, tomorrow) read:
#     "Test Files  3 failed | 697 passed | 1 skipped (701) | Tests  3 failed | 12911 passed"
# -- three of 12,925 tests failed, and nothing about WHICH. An aggregate is a fact, not a
# diagnosis, so named lines are selected first and the aggregate only fills what is left.

VITEST_GREEN = "\n".join(
    " ✓ server/utils/otc/%s.test.ts (%d tests) %dms" % (n, 9 + n % 7, 4 + n % 30)
    for n in range(400))

VITEST_REAL = VITEST_GREEN + "\n" + "\n".join([
    " ❯ server/utils/__tests__/tracing.test.ts (6 tests | 1 failed) 22ms",
    "   × tracing.withSpan > clears currentSpan after returning",
    "     AssertionError: expected undefined to be 'root-span'",
    " Test Files  3 failed | 697 passed | 1 skipped (701)",
    "      Tests  3 failed | 12911 passed | 11 skipped (12925)",
])


def _gate_window(text):
    """What _run_tests hands the caller: the last 6,000 characters."""
    return text[-6000:].strip()


def test_the_old_selection_returns_pure_passing_output_on_this_shape():
    """The live failure mode, pinned: hundreds of green lines fill the window."""
    window = _gate_window(VITEST_REAL)
    old = window[:200]
    assert "✓" in old
    assert "AssertionError" not in old
    assert "failed" not in old


def test_the_excerpt_names_the_failing_test():
    out = failure_excerpt.excerpt(_gate_window(VITEST_REAL), 240)
    assert "tracing.withSpan > clears currentSpan after returning" in out


def test_the_excerpt_names_the_failing_file():
    out = failure_excerpt.excerpt(_gate_window(VITEST_REAL), 240)
    assert "tracing.test.ts" in out


def test_the_excerpt_does_not_lead_with_the_aggregate():
    out = failure_excerpt.excerpt(_gate_window(VITEST_REAL), 240)
    assert not out.strip().startswith("Test Files")


def test_the_aggregate_is_still_available_when_it_is_all_there_is():
    """A runner that prints only a summary must still yield something."""
    only_counts = VITEST_GREEN + "\n Test Files  3 failed | 697 passed (700)\n"
    out = failure_excerpt.excerpt(_gate_window(only_counts), 240)
    assert "3 failed" in out


def test_specific_lines_sort_ahead_of_aggregates():
    lines = failure_excerpt.failure_lines(VITEST_REAL)
    first_specific = next(i for i, l in enumerate(lines) if "tracing.test.ts" in l)
    first_aggregate = next(i for i, l in enumerate(lines) if l.strip().startswith("Test Files"))
    assert first_specific < first_aggregate


def test_a_tsc_error_outranks_a_count_line():
    text = "Tests  4 failed | 90 passed\nsrc/pricing.ts:88:14 - error TS2345: bad arg\n"
    out = failure_excerpt.excerpt(text, 80)
    assert "error TS2345" in out
