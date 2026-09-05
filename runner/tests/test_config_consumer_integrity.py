#!/usr/bin/env python3
"""Narrow integrity guard for runner/config_consumer.py.

WHAT THIS ADDS OVER THE EXISTING TESTS
--------------------------------------
`test_config_consumer.py` and `test_config_consumer_knobs.py` already cover behaviour
well (71 cases between them). What neither does is assert on the file *as bytes*, and
that is the gap this file closes.

Behavioural tests import the module, so an unresolved conflict marker makes them ERROR
at collection with a `SyntaxError` pointing at a line number — a symptom that reads like
a broken test rather than a corrupted source file. The task that spawned this test was
opened on exactly that mis-signal: it asserted config_consumer.py had markers and was
breaking the build, when in fact the file was clean. A cheap explicit check makes the
answer to "is this file intact?" unambiguous in both directions.

Deliberately NOT repo-wide. Four files under hisanta/ carry committed conflict markers
on origin/master today, so a repo-wide guard would be red on arrival — the exact
failure mode `.github/workflows/ci.yml` warns about, where a permanently-failing job
teaches people to ignore CI. Those are filed separately as their own bugfix.
"""
import os
import re
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _RUNNER)

MODULE_PATH = os.path.join(_RUNNER, "config_consumer.py")

# Anchored to line start: a marker only counts as a conflict marker in column 0. Without
# the anchor this test would flag its own docstring and any string literal mentioning one.
_MARKERS = (
    re.compile(r"^<{7}(?: |$)", re.M),
    re.compile(r"^={7}$", re.M),
    re.compile(r"^>{7}(?: |$)", re.M),
)

# The surface other modules actually import. Losing any of these silently is the failure
# a marker-only check would miss: a bad merge that drops a function leaves valid Python.
PUBLIC_API = ("load_all", "get", "get_int", "get_bool", "get_float",
              "load_config", "invalidate_cache")


@pytest.fixture(scope="module")
def source():
    with open(MODULE_PATH, encoding="utf-8", errors="replace") as handle:
        return handle.read()


# ── the file is intact ──────────────────────────────────────────────────────

def test_module_file_exists():
    assert os.path.isfile(MODULE_PATH)


def test_source_has_no_conflict_markers(source):
    found = [m.pattern for m in _MARKERS if m.search(source)]
    assert not found, (
        f"runner/config_consumer.py contains git conflict markers {found}. "
        "Resolve the merge; do not delete the markers without picking a side.")


def test_source_compiles(source):
    """Catches marker-adjacent damage that is not literally a marker."""
    compile(source, MODULE_PATH, "exec")


# ── the module is usable ────────────────────────────────────────────────────

def test_module_imports():
    import config_consumer  # noqa: F401


@pytest.mark.parametrize("name", PUBLIC_API)
def test_public_api_is_present_and_callable(name):
    import config_consumer
    assert callable(getattr(config_consumer, name, None)), \
        f"config_consumer.{name} is missing — a merge may have dropped it"


def test_getters_work_against_a_minimal_config(monkeypatch):
    """Exercise the real read path end to end, not just getattr on the module.

    Keys are read as ORCH_{key} from the environment, so the fixture is env vars —
    matching how test_config_consumer.py drives the same surface.
    """
    import config_consumer

    monkeypatch.setenv("ORCH_INTEGRITY_X", "7")
    monkeypatch.setenv("ORCH_INTEGRITY_FLAG", "true")
    config_consumer.invalidate_cache()

    assert config_consumer.get("INTEGRITY_X") == "7"
    assert config_consumer.get_int("INTEGRITY_X") == 7
    assert config_consumer.get_float("INTEGRITY_X") == 7.0
    assert config_consumer.get_bool("INTEGRITY_FLAG") is True
    assert "INTEGRITY_X" in config_consumer.load_all()


def test_getters_return_defaults_for_unknown_keys(monkeypatch):
    """Fail-soft is the documented convention: an absent key is a default, not a raise."""
    import config_consumer

    monkeypatch.delenv("ORCH_INTEGRITY_ABSENT", raising=False)
    config_consumer.invalidate_cache()

    assert config_consumer.get("INTEGRITY_ABSENT", "fallback") == "fallback"
    assert config_consumer.get_int("INTEGRITY_ABSENT", 3) == 3
    assert config_consumer.get_bool("INTEGRITY_ABSENT", False) is False
    assert config_consumer.get_float("INTEGRITY_ABSENT", 1.5) == 1.5


def test_invalidate_cache_accepts_both_forms():
    import config_consumer
    config_consumer.invalidate_cache()          # whole cache
    config_consumer.invalidate_cache("ORCH_X")  # single key


# ── the guard itself works ──────────────────────────────────────────────────

def test_the_marker_check_would_actually_catch_a_marker():
    """A guard nobody has seen fail is a guard nobody knows works."""
    corrupted = "a = 1\n" + "<" * 7 + " HEAD\nb = 2\n" + "=" * 7 + "\nb = 3\n" + \
                ">" * 7 + " agent/x\n"
    assert any(m.search(corrupted) for m in _MARKERS)


def test_the_marker_check_does_not_fire_on_prose_mentioning_markers():
    assert not any(m.search("# a merge leaves <<<<<<< in the file\n") for m in _MARKERS)
