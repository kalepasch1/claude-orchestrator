"""Verification that crash_loop_detector actually FIRES and ALERTS on a 100%-dead module.

Failure class 6: preflight raised on every invocation for 19 days and nobody noticed. The
detector exists, but "the detector exists" was also true of several guards that turned out
to be inert, so these tests assert the whole chain rather than the parse step alone:

  scan() sees the dead module -> classify() ranks it critical -> _should_fire() lets it
  through -> _alert() reaches BOTH a notification and an approvals card.

The last link is the one that matters. A finding that is logged to a JSONL file nobody opens
is indistinguishable from silence, which is the failure mode this class is about.

The fixture reproduces the preflight shape exactly: a .err file full of identical tracebacks
and a .log file that is empty (no successful output has ever been produced).
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault("db", type(sys)("db"))
import crash_loop_detector as cld  # noqa: E402

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/preflight.py", '
    "line 88, in run\n"
    "    gate = _resolve_gate(project)\n"
    '  File "/Users/kpasch/Documents/beethoven/claude-orchestrator/runner/preflight.py", '
    "line 41, in _resolve_gate\n"
    "    return CONFIG['gate']\n"
    "KeyError: 'gate'\n")


def _dead_module_logs(tmp_path, job="preflight", attempts=40, empty_log=True):
    """A job whose every invocation crashed and which produced no successful output."""
    err = tmp_path / (job + ".err")
    err.write_text("\n".join(TRACEBACK for _ in range(attempts)))
    log = tmp_path / (job + ".log")
    log.write_text("" if empty_log else "ok\n")
    if not empty_log:
        # Successful output that stopped long before the crashes began.
        old = time.time() - (cld.STALE_LOG_S + 86400)
        os.utime(str(log), (old, old))
    return tmp_path


# ------------------------------------------------------------------ fires on the incident

def test_scan_marks_the_module_dead(tmp_path):
    jobs = cld.scan(str(_dead_module_logs(tmp_path)))
    assert "preflight" in jobs, "the .err file must be picked up"
    assert jobs["preflight"]["module_dead"] is True, \
        "an all-crash job with no successful output is 100% dead"


def test_classify_ranks_it_critical(tmp_path):
    findings = cld.classify(cld.scan(str(_dead_module_logs(tmp_path))))
    assert findings, "a dead module must produce a finding"
    top = findings[0]
    assert top["job"] == "preflight"
    assert top["severity"] == "critical"
    assert "module_dead" in top["reasons"]
    assert "KeyError" in top["exception"]


def test_dead_module_detected_when_log_is_merely_stale(tmp_path):
    """The other dead shape: it used to work, then every run started failing."""
    jobs = cld.scan(str(_dead_module_logs(tmp_path, empty_log=False)))
    assert jobs["preflight"]["module_dead"] is True


def test_fires_on_first_sight(tmp_path):
    findings = cld.classify(cld.scan(str(_dead_module_logs(tmp_path))))
    fire, why = cld._should_fire(findings[0], {}, time.time())
    assert fire is True and why == "new"


def test_alert_reaches_a_human_surface(tmp_path, monkeypatch):
    """THE test for this class: the finding must escape the log file.

    19 days of silence happened because nothing carried the failure to a surface a person
    looks at. Assert both channels: a notification AND a durable approvals card.
    """
    findings = cld.classify(cld.scan(str(_dead_module_logs(tmp_path))))
    sent, cards = [], []

    fake_notify = type(sys)("notify")
    fake_notify.send = lambda msg, *a, **kw: sent.append(msg)
    monkeypatch.setitem(sys.modules, "notify", fake_notify)
    monkeypatch.setattr(cld.db, "insert", lambda table, row, **kw: cards.append((table, row)),
                        raising=False)

    cld._alert(findings[0])

    assert sent, "a 100%-dead module must raise a notification"
    assert "preflight" in sent[0]
    assert "100% DEAD" in sent[0], "the headline must say the module is dead, not just noisy"

    assert cards, "a 100%-dead module must leave a durable approvals card"
    table, row = cards[0]
    assert table == "approvals"
    assert "preflight" in row["title"]
    assert row["status"] == "pending", "the card must require a human decision"
    assert "KeyError" in row["risk"], "the card must carry the traceback"


def test_alert_survives_a_missing_notify_module(tmp_path, monkeypatch):
    """Alerting must be fail-soft: a broken channel cannot suppress the approvals card."""
    findings = cld.classify(cld.scan(str(_dead_module_logs(tmp_path))))
    cards = []
    broken = type(sys)("notify")

    def boom(*a, **kw):
        raise OSError("notification backend down")

    broken.send = boom
    monkeypatch.setitem(sys.modules, "notify", broken)
    monkeypatch.setattr(cld.db, "insert", lambda table, row, **kw: cards.append(row),
                        raising=False)
    cld._alert(findings[0])
    assert cards, "the card must still be written when the notifier fails"


def test_registered_in_the_schedule():
    """A detector that is not dispatched is exactly as silent as no detector."""
    runner_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "runner.py")).read()
    periodic_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "periodic.py")).read()
    assert '"crashloop"' in runner_src, "crashloop missing from runner._SCHEDULE"
    assert '"crashloop": run_crashloop' in periodic_src, "crashloop missing from periodic.JOBS"


# ------------------------------------------------------------- clean controls (no FPs)

def test_healthy_job_does_not_fire(tmp_path):
    """A job that crashed a couple of times but keeps succeeding is not a crash loop."""
    (tmp_path / "healthy.err").write_text(TRACEBACK * 2)
    (tmp_path / "healthy.log").write_text("run ok\n" * 500)
    findings = cld.classify(cld.scan(str(tmp_path)))
    assert findings == [], "an occasional traceback in a working job must not alert"


def test_transient_infrastructure_errors_do_not_fire(tmp_path):
    """Network weather is not a dead module; alerting on it trains people to ignore alerts."""
    transient = ("Traceback (most recent call last):\n"
                 '  File "runner/db.py", line 10, in get\n'
                 "    resp = urlopen(url)\n"
                 "ConnectionResetError: [Errno 54] Connection reset by peer\n")
    (tmp_path / "flaky.err").write_text(transient * 6)
    (tmp_path / "flaky.log").write_text("ok\n" * 200)
    findings = [f for f in cld.classify(cld.scan(str(tmp_path))) if not f["transient"]]
    assert findings == []


def test_empty_log_dir_is_silent(tmp_path):
    assert cld.scan(str(tmp_path)) == {}
    assert cld.classify({}) == []


def test_second_alert_is_deduplicated(tmp_path):
    """Re-alerting every cycle is its own kind of silence."""
    findings = cld.classify(cld.scan(str(_dead_module_logs(tmp_path))))
    top = findings[0]
    state = {top["signature"]: {"last_alert": time.time(), "count_at_alert": top["count"]}}
    fire, _ = cld._should_fire(top, state, time.time())
    assert fire is False
