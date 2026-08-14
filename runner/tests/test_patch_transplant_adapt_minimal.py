#!/usr/bin/env python3
"""Minimal correctness test for the patch-transplant adaptation core.

Scope is deliberately narrow: it exercises `patch_transplant.adapt_patch` and
`patch_transplant.hint` directly, with no DB, no network and no fixtures, so a
regression in the transplant path fails here before any model spend happens.

Covers only the behaviour the transplant path actually depends on:
  1. the adapted diff keeps the caller's type (str in -> str out, bytes in ->
     bytes out), because `apply_patch` re-encodes and a silent type flip
     produced a double-encode in the original defect;
  2. diff headers are rewritten onto the target file ONLY when the prior diff
     targets none of the requested files -- rewriting per-file clobbered the
     earlier match;
  3. an already-marked prompt is never re-hinted (idempotent pre_claim_hook).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import patch_transplant  # noqa: E402


PRIOR_DIFF = (
    "--- a/runner/old_module.py\n"
    "+++ b/runner/old_module.py\n"
    "@@ -1,2 +1,3 @@\n"
    " import os\n"
    "+import sys\n"
)


def test_empty_prior_diff_is_not_adaptable():
    """No prior diff means no transplant -- the caller must fall back."""
    assert patch_transplant.adapt_patch("", {"slug": "s"}) is None
    assert patch_transplant.adapt_patch(None, {"slug": "s"}) is None


def test_adapt_patch_preserves_caller_type():
    """str in -> str out, bytes in -> bytes out (apply_patch re-encodes)."""
    as_str = patch_transplant.adapt_patch(PRIOR_DIFF, {"slug": "s"})
    assert isinstance(as_str, str)

    as_bytes = patch_transplant.adapt_patch(PRIOR_DIFF.encode("utf-8"), {"slug": "s"})
    assert isinstance(as_bytes, bytes)
    assert as_bytes.decode("utf-8") == as_str


def test_headers_rewritten_when_prior_diff_misses_every_target():
    adapted = patch_transplant.adapt_patch(
        PRIOR_DIFF, {"slug": "s"}, target_files=["runner/new_module.py"]
    )
    assert "--- a/runner/new_module.py" in adapted
    assert "+++ b/runner/new_module.py" in adapted
    assert "old_module.py" not in adapted
    # the body is content, not a header, and must survive untouched
    assert "+import sys" in adapted


@pytest.mark.parametrize(
    "target_files",
    [
        ["runner/old_module.py"],          # exact path match
        ["old_module.py"],                  # basename match
        ["old_module.py", "other.py"],      # match is not required to be first
    ],
)
def test_headers_left_alone_when_prior_diff_already_targets_a_requested_file(target_files):
    """Rewriting here would clobber a diff that was already on target."""
    adapted = patch_transplant.adapt_patch(PRIOR_DIFF, {"slug": "s"}, target_files=target_files)
    assert adapted == PRIOR_DIFF


def test_hint_is_idempotent_for_an_already_marked_prompt():
    """A prompt carrying the mark must not be hinted a second time."""
    task = {"id": "t1", "slug": "s", "prompt": f"{patch_transplant.MARK}: already adapted"}
    assert patch_transplant.hint(task) == ""
    # pre_claim_hook must then be a pure no-op -- same object contents, no DB write
    assert patch_transplant.pre_claim_hook(task) == task
