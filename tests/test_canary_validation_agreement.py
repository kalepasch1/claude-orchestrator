"""All canary-marker entry points must return the same verdict.

There are three importable `validate_canary` functions in this repo:

    canary.validate_canary                    (repo root, CLI entrypoint)
    runner.canary.validate_canary             (metrics/canary server)
    runner.canary_validation.validate_canary  (owner module)

They disagreed: the runner/canary.py copy matched "canary" as a SUBSTRING while
the other two matched on a WORD BOUNDARY, so "precanary" validated at one entry
point and failed at the others. A marker check whose job is to prove a canary
survived a pipeline hop must not depend on which import the caller reached for.

This is the narrowest check that proves the requested behaviour: it pins the
agreement rather than re-testing each implementation separately, so a future
divergence fails here no matter which copy drifts.
"""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNNER = REPO_ROOT / "runner"
if str(RUNNER) not in sys.path:
    sys.path.insert(0, str(RUNNER))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module)
    spec.loader.exec_module(module)
    return module

root_canary = _load("root_canary", REPO_ROOT / "canary.py")
import canary as runner_canary  # noqa: E402  (runner/ is on sys.path above)
import canary_validation  # noqa: E402

IMPLEMENTATIONS = [
    pytest.param(root_canary.validate_canary, id="root/canary.py"),
    pytest.param(runner_canary.validate_canary, id="runner/canary.py"),
    pytest.param(canary_validation.validate_canary, id="runner/canary_validation.py"),
]

# (text, expected). The word-boundary cases are the ones that used to disagree.
CASES = [
    ("canary", True),
    ("Canary bird", True),
    ("CANARY", True),
    ("the canary sang", True),
    ("a canary.", True),
    ("nothing", False),
    ("", False),
    ("precanary", False),      # substring match wrongly said True
    ("canaryX", False),        # substring match wrongly said True
    ("canaries", False),       # substring match wrongly said True
]


@pytest.mark.parametrize("func", IMPLEMENTATIONS)
@pytest.mark.parametrize("text,expected", CASES)
def test_every_implementation_agrees(func, text, expected):
    assert func(text) is expected, f"{func.__module__}.validate_canary({text!r})"


@pytest.mark.parametrize("func", IMPLEMENTATIONS)
@pytest.mark.parametrize("bad", [None, 42, [], {}, object()])
def test_non_string_input_is_fail_soft_everywhere(func, bad):
    """Fail-soft means False, never an exception — a validator must not crash the hop."""
    assert func(bad) is False


@pytest.mark.parametrize("text,expected", CASES)
def test_implementations_are_mutually_consistent(text, expected):
    """Explicitly compare the copies, so drift in any one of them fails here."""
    verdicts = {
        "root": root_canary.validate_canary(text),
        "runner": runner_canary.validate_canary(text),
        "owner": canary_validation.validate_canary(text),
    }
    assert len(set(verdicts.values())) == 1, f"divergent verdicts for {text!r}: {verdicts}"
    assert verdicts["owner"] is expected


def test_cli_exit_code_contract():
    """`python canary.py <text>` exits 0 on hit, 1 on miss — pipelines gate on this."""
    assert root_canary.main(["a canary here"]) == 0
    assert root_canary.main(["nothing at all"]) == 1
    assert root_canary.main(["precanary"]) == 1
