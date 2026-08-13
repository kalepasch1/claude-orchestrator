"""Large merge diffs must be processed chunk-by-chunk, never in one turn.

The merged-diff-memory run for session f5e66127 died with ``error_max_turns``
after 2 turns because the whole merge diff was handed to the model at once, and
the failure took the *entire* capture with it. These tests pin the two
properties that prevent a repeat: every chunk stays under the line ceiling, and
a failing chunk still leaves the successful ones as a partial merge.
"""
import os
import sys

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
)
import diff_chunker as dc


def _file_diff(path, body_lines):
    header = (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -0,0 +1,{body_lines} @@\n"
    )
    return header + "".join(f"+line {i}\n" for i in range(body_lines))


# --- chunking -------------------------------------------------------------

def test_empty_and_none_return_no_chunks():
    assert dc.chunk_diff("") == []
    assert dc.chunk_diff(None) == []
    assert dc.split_diff_by_file(None) == []


def test_small_diff_is_a_single_chunk():
    diff = _file_diff("a.py", 10)
    chunks = dc.chunk_diff(diff, max_lines=500)
    assert len(chunks) == 1
    assert chunks[0] == diff


def test_splits_on_file_boundaries():
    diff = _file_diff("a.py", 5) + _file_diff("b.py", 5)
    chunks = dc.chunk_diff(diff, max_lines=500)
    assert len(chunks) == 2
    assert chunks[0].startswith("diff --git a/a.py")
    assert chunks[1].startswith("diff --git a/b.py")


def test_large_single_file_is_hard_split_under_the_ceiling():
    diff = _file_diff("big.py", 2000)
    chunks = dc.chunk_diff(diff, max_lines=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.splitlines()) <= 500


def test_no_content_is_lost_when_splitting():
    diff = _file_diff("big.py", 1200) + _file_diff("other.py", 700)
    assert "".join(dc.chunk_diff(diff, max_lines=500)) == diff


def test_preamble_before_first_file_header_is_kept():
    diff = "commit abc123\nAuthor: someone\n\n" + _file_diff("a.py", 3)
    assert "".join(dc.chunk_diff(diff, max_lines=500)) == diff


# --- retry loop / partial merges ------------------------------------------

def test_large_diff_completes_without_max_turn_errors():
    """The regression: a 5000-line diff used to be one oversized unit of work."""
    diff = _file_diff("huge.py", 5000)
    seen = []

    def processor(chunk, index, total):
        # Stand-in for the model call. A chunk over the turn budget is exactly
        # what produced error_max_turns; assert we never hand one over.
        assert len(chunk.splitlines()) <= 500, "chunk exceeds turn budget"
        seen.append(index)
        return len(chunk.splitlines())

    result = dc.process_diff_chunked(diff, processor, max_lines=500)

    assert result["complete"] is True
    assert result["failed"] == []
    assert result["chunks"] > 1
    assert result["succeeded"] == result["chunks"]
    assert seen == list(range(result["chunks"]))


def test_failing_chunk_is_retried_then_recorded_as_partial():
    diff = _file_diff("a.py", 5) + _file_diff("b.py", 5)
    attempts = {"count": 0}

    def processor(chunk, index, total):
        if index == 1:
            attempts["count"] += 1
            raise RuntimeError("model timed out")
        return "ok"

    result = dc.process_diff_chunked(diff, processor, max_lines=500, max_retries=3)

    assert attempts["count"] == 3            # retried, not abandoned
    assert result["results"] == ["ok"]       # partial merge survives
    assert result["succeeded"] == 1
    assert result["complete"] is False
    assert result["failed"][0]["index"] == 1
    assert "model timed out" in result["failed"][0]["error"]


def test_transient_failure_recovers_on_retry():
    diff = _file_diff("a.py", 5)
    state = {"n": 0}

    def processor(chunk, index, total):
        state["n"] += 1
        if state["n"] < 2:
            raise RuntimeError("transient")
        return "recovered"

    result = dc.process_diff_chunked(diff, processor, max_lines=500, max_retries=3)
    assert result["complete"] is True
    assert result["results"] == ["recovered"]


def test_bad_processor_is_fail_soft():
    result = dc.process_diff_chunked(_file_diff("a.py", 3), None)
    assert result["complete"] is False
    assert result["results"] == []


def test_empty_diff_short_circuits():
    result = dc.process_diff_chunked("", lambda c, i, t: 1)
    assert result == {"results": [], "chunks": 0, "succeeded": 0,
                      "failed": [], "complete": True}
