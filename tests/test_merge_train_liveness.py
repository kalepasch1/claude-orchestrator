"""A merge stall has two causes and they need opposite fixes.

On 2026-08-24 the fleet went ~18h with zero MERGED transitions while DONE
completions continued at full rate. Three priority-1000 tasks were opened against
``merge_train.py`` and all three reached DONE without merges resuming, because the
actual condition was that the ``com.claudeorchestrator.runner`` launchd agent —
the only thing that calls ``merge_train.run()`` — was not registered at all.

These tests pin the distinction: NO_CONSUMER (nobody is executing the code) must
never be reported as CONSUMER_STALLED (the code is executing and failing), because
the remedies are unrelated and the wrong one costs a day.
"""
import os
import sys
import time

import pytest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
)
import merge_train_liveness as mtl


@pytest.fixture
def fresh_log(tmp_path):
    p = tmp_path / "merge-train.log"
    p.write_text("merge_train: 1 merged\n")
    return str(p)


@pytest.fixture
def stale_log(tmp_path):
    p = tmp_path / "stale-merge-train.log"
    p.write_text("merge_train: 0 merged\n")
    old = time.time() - (mtl.LOG_STALE_HOURS + 24) * 3600
    os.utime(str(p), (old, old))
    return str(p)


# --- the 2026-08-24 case: nothing is running the merge train ----------------

def test_unloaded_agent_is_no_consumer(monkeypatch, fresh_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: False)
    d = mtl.diagnose(log_path=fresh_log, merges_recent=False)
    assert d["diagnosis"] == mtl.NO_CONSUMER
    assert "not registered" in d["reason"]


def test_stale_log_is_no_consumer_even_if_agent_looks_loaded(monkeypatch, stale_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: True)
    d = mtl.diagnose(log_path=stale_log, merges_recent=False)
    assert d["diagnosis"] == mtl.NO_CONSUMER


def test_no_consumer_remedy_does_not_point_at_merge_train_internals(monkeypatch, fresh_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: False)
    d = mtl.diagnose(log_path=fresh_log, merges_recent=False)
    assert "launchctl" in d["remedy"]
    assert "repo_lock" not in d["remedy"]


# --- the 2026-07-08 case: the consumer runs and fails -----------------------

def test_live_consumer_without_merges_is_consumer_stalled(monkeypatch, fresh_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: True)
    d = mtl.diagnose(log_path=fresh_log, merges_recent=False)
    assert d["diagnosis"] == mtl.CONSUMER_STALLED
    assert "repo_lock" in d["remedy"]


def test_live_consumer_with_merges_is_ok(monkeypatch, fresh_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: True)
    d = mtl.diagnose(log_path=fresh_log, merges_recent=True)
    assert d["diagnosis"] == mtl.OK


def test_the_two_diagnoses_are_never_confused(monkeypatch, fresh_log, stale_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: True)
    live = mtl.diagnose(log_path=fresh_log, merges_recent=False)["diagnosis"]
    dead = mtl.diagnose(log_path=stale_log, merges_recent=False)["diagnosis"]
    assert live != dead


# --- unknown must never be reported as a dead consumer ----------------------

def test_unknown_agent_state_with_fresh_log_is_not_no_consumer(monkeypatch, fresh_log):
    """A non-macOS host has no launchctl. That is ignorance, not an outage."""
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: None)
    d = mtl.diagnose(log_path=fresh_log, merges_recent=True)
    assert d["diagnosis"] != mtl.NO_CONSUMER


def test_no_evidence_at_all_is_unknown(monkeypatch, tmp_path):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: None)
    d = mtl.diagnose(log_path=str(tmp_path / "nope.log"), merges_recent=False)
    assert d["diagnosis"] == mtl.UNKNOWN


# --- fail-soft contract -----------------------------------------------------

def test_missing_log_returns_none_not_raise(tmp_path):
    assert mtl.log_age_hours(str(tmp_path / "absent.log")) is None


def test_empty_path_is_unknowable_not_an_outage():
    """"" is not a path. Answering "stale" for it would fabricate an outage."""
    assert mtl.log_age_hours("") is None


def test_launchd_agent_loaded_tolerates_empty_label():
    assert mtl.launchd_agent_loaded("") is None


def test_launchctl_failure_is_unknown_not_false(monkeypatch):
    def boom(*a, **k):
        raise OSError("launchctl missing")

    monkeypatch.setattr(mtl.subprocess, "run", boom)
    assert mtl.launchd_agent_loaded("com.example.thing") is None


def test_launchctl_nonzero_exit_is_unknown(monkeypatch):
    class R:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(mtl.subprocess, "run", lambda *a, **k: R())
    assert mtl.launchd_agent_loaded("com.example.thing") is None


def test_launchctl_parses_label_from_last_column(monkeypatch):
    class R:
        returncode = 0
        stdout = "-\t0\tcom.claudeorchestrator.chatgptbridge\n123\t0\tcom.other\n"

    monkeypatch.setattr(mtl.subprocess, "run", lambda *a, **k: R())
    assert mtl.launchd_agent_loaded("com.claudeorchestrator.chatgptbridge") is True
    assert mtl.launchd_agent_loaded("com.claudeorchestrator.runner") is False


def test_diagnose_never_raises_on_broken_probe(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(mtl, "launchd_agent_loaded", boom)
    d = mtl.diagnose(merges_recent=False)
    assert d["diagnosis"] == mtl.UNKNOWN


def test_summary_line_is_one_line_and_never_raises(monkeypatch):
    monkeypatch.setattr(mtl, "diagnose", lambda **k: (_ for _ in ()).throw(RuntimeError()))
    line = mtl.summary_line()
    assert "\n" not in line
    assert mtl.UNKNOWN in line


def test_summary_line_carries_the_diagnosis(monkeypatch, stale_log):
    monkeypatch.setattr(mtl, "launchd_agent_loaded", lambda label=None: False)
    line = mtl.summary_line(log_path=stale_log, merges_recent=False)
    assert mtl.NO_CONSUMER in line


# --- configuration is fleet-pushable ---------------------------------------

def test_thresholds_are_orch_prefixed_env_vars():
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "runner", "merge_train_liveness.py")
    ).read()
    for key in ("ORCH_MERGE_TRAIN_LAUNCHD_LABEL", "ORCH_MERGE_TRAIN_LOG_STALE_HOURS"):
        assert key in src


def test_stall_monitor_alert_names_the_liveness_case():
    """The alert must not send operators at merge_train.py when nothing runs it."""
    src = open(
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "runner", "merge_stall_monitor.py")
    ).read()
    assert "merge_train_liveness" in src
    assert "NO_CONSUMER" in src
