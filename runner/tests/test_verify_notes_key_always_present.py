"""verify.review_diff must always return a dict with a `notes` key.

Root cause of the `orphaned-running` repair-task family:

    File "runner/runner.py", line 2770, in run_task
        result = integrate(repo, f"agent/{slug}", base, test_cmd, slug, v["notes"], ...)
    KeyError: 'notes'

`v` is whatever JSON the review model emitted. `{"verdict": "pass"}` with no
`notes` is a perfectly ordinary completion, and review_diff normalised `verdict`
but not `notes`. The KeyError fired on the SUCCESS path -- after the agent had
already built, tested and committed the branch -- so the completed work was
discarded and the sweeper requeued the task as a repair.

These tests pin the contract at the source (review_diff) and at the call sites
in runner.py that read the key positionally.
"""
import re
import sys
import pathlib

import pytest

RUNNER_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RUNNER_DIR))

import verify  # noqa: E402

FAKE_DIFF = "diff --git a/x.py b/x.py\n+++ b/x.py\n@@\n+print('hello')\n"


def _review(monkeypatch, model_text):
    """Run review_diff against a canned model response and a canned diff."""
    monkeypatch.setattr(verify.subprocess, "check_output",
                        lambda *a, **k: FAKE_DIFF)
    monkeypatch.setattr(verify, "REVIEW_MODEL", "canned", raising=False)

    class _Gateway:
        @staticmethod
        def complete(*a, **k):
            return {"text": model_text, "provider": "test", "model": "canned"}

        @staticmethod
        def provider_for_model(_m):
            return "test"

    monkeypatch.setattr(verify, "model_gateway", _Gateway)
    return verify.review_diff("/tmp", "main")


@pytest.mark.parametrize("model_text", [
    '{"verdict": "pass"}',                         # the exact shape that crashed
    '{"verdict":"pass","score":8}',                # notes omitted, other keys present
    '{"verdict": "fail"}',                         # fail path, notes omitted
    'sure! here you go: {"verdict":"pass"} done',  # JSON embedded in prose
    'no json here at all',                         # unparseable
])
def test_review_diff_always_has_notes(monkeypatch, model_text):
    d = _review(monkeypatch, model_text)
    assert "notes" in d, f"review_diff dropped `notes` for model output {model_text!r}"
    assert isinstance(d["notes"], str)
    # The crash was `"verify: " + v["notes"]` -- concatenation must not raise.
    assert isinstance("verify: " + d["notes"], str)


def test_review_diff_preserves_supplied_notes(monkeypatch):
    d = _review(monkeypatch, '{"verdict": "pass", "notes": "looks fine"}')
    assert d["notes"] == "looks fine", "defaulting must not clobber real notes"


def test_runner_never_subscripts_verify_notes():
    """No live call site may read `notes` with [] -- that is what raised KeyError.

    Guards against the fix being silently reverted by a later edit.
    """
    src = (RUNNER_DIR / "runner.py").read_text()
    code = "\n".join(
        line for line in src.splitlines() if not line.lstrip().startswith("#")
    )
    offenders = re.findall(r'\bv\["notes"\]', code)
    assert not offenders, (
        f'runner.py still subscripts v["notes"] in {len(offenders)} place(s); '
        'use v.get("notes") or "" -- this is the KeyError: \'notes\' regression'
    )
