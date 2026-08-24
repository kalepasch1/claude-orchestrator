"""A control plane outage must not present as a crash in integration_sweeper.

Losing DNS let db.TransientDBError escape main() as an unhandled traceback on
every scheduled run. The result was 3951 tracebacks in
.runtime/logs/integration-sweeper.err — 64% of everything this job has ever
logged — none of them actionable, and all of them burying the failures that
are. The job was "failing silently" precisely because it was failing so loudly
about something it could do nothing about.

The contract these tests pin:
  * a transient control-plane error exits EX_TEMPFAIL with a one-line
    diagnostic, and does NOT raise;
  * it does NOT exit 0 — the sweep did not run, and reporting success for work
    that never happened is the silent failure the job was filed for;
  * a real error is still raised, so this cannot become a blanket swallow.
"""
import os
import sys

import pytest

_RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RUNNER not in sys.path:
    sys.path.insert(0, _RUNNER)

import db  # noqa: E402
import integration_sweeper as isw  # noqa: E402


DNS_FAILURE = ("all Supabase endpoints unreachable for GET /rest/v1/tasks: "
               "<urlopen error [Errno 8] nodename nor servname provided, or not known>")


class _Args:
    verify_phantom = False
    project = None
    limit = 1
    dry_run = True
    include_quarantined = False
    no_train = True


@pytest.fixture()
def args(monkeypatch):
    """Bypass argparse so the tests drive main()'s error handling directly."""
    class _Parser:
        def parse_args(self, argv=None):
            return _Args()

    monkeypatch.setattr(isw, "_build_parser", lambda: _Parser())
    return _Args()


def test_transient_db_error_exits_tempfail(args, monkeypatch, capsys):
    monkeypatch.setattr(isw, "sweep",
                        lambda *a, **k: (_ for _ in ()).throw(db.TransientDBError(DNS_FAILURE)))
    assert isw.main([]) == isw.EX_TEMPFAIL


def test_transient_db_error_does_not_report_success(args, monkeypatch):
    """Exit 0 would claim a sweep happened. It did not."""
    monkeypatch.setattr(isw, "sweep",
                        lambda *a, **k: (_ for _ in ()).throw(db.TransientDBError(DNS_FAILURE)))
    assert isw.main([]) != 0


def test_transient_db_error_is_not_raised(args, monkeypatch):
    """No traceback: that is the whole point."""
    monkeypatch.setattr(isw, "sweep",
                        lambda *a, **k: (_ for _ in ()).throw(db.TransientDBError(DNS_FAILURE)))
    isw.main([])  # must not raise


def test_diagnostic_names_the_cause_on_stderr(args, monkeypatch, capsys):
    monkeypatch.setattr(isw, "sweep",
                        lambda *a, **k: (_ for _ in ()).throw(db.TransientDBError(DNS_FAILURE)))
    isw.main([])
    err = capsys.readouterr().err
    assert "control plane unreachable" in err
    assert "transient" in err
    assert "nodename nor servname" in err
    assert "Traceback" not in err


def test_a_real_error_still_surfaces(args, monkeypatch):
    """Not a blanket swallow — only the transient class is absorbed."""
    monkeypatch.setattr(isw, "sweep",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("genuine bug")))
    with pytest.raises(ValueError):
        isw.main([])


def test_successful_sweep_still_exits_zero(args, monkeypatch):
    monkeypatch.setattr(isw, "sweep", lambda *a, **k: {"merged": []})
    assert isw.main([]) == 0


def test_tempfail_is_the_sysexits_value():
    """75 is EX_TEMPFAIL; schedulers and crash detectors key off it."""
    assert isw.EX_TEMPFAIL == 75
