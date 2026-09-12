"""A parentless home-directory scan is pure load, and load throttles the fleet.

MEASURED 2026-09-03. Load average 67 on this Mac, with merge_train's own CPU clamp
doing exactly what it was built to do in response:

    merge_train: load/core 7.69 (soft 1.5 hard 3.0) — running 1 project worker(s)
                 instead of 4

Two of the top four CPU consumers were parentless searches:

    bfs -S dfs ... /Users/kpasch -type d -name sustainable-barks   11m58s, 82.6%
    bfs -S dfs ... /Users/kpasch -type d -name *pareto*             4m42s, 68.1%

Both ppid 1, both children of `/bin/zsh -c source ~/.claude/shell-snapshots/...` --
agent sessions that had already exited. An agent that does not know where a repo
lives searches the whole home directory for it, and when the session ends the search
is reparented to launchd where nothing can ever read its result. Killing the first
took the load average from 67 to 31 inside a minute.

reap_orphaned_builds() did not catch these: its markers are build and test tools.
"""
import resource_medic as medic

HOME = "/Users/kpasch"


def _ps(*rows):
    return "\n".join(rows)


def _row(pid, ppid, etime, cmd):
    return f"  {pid}  {ppid} {etime} {cmd}"


def _fake_ps(monkeypatch, text):
    class Result:
        stdout = text

    monkeypatch.setattr(medic, "sh", lambda *a, **k: Result())


def test_the_two_processes_that_held_this_mac_at_load_67_are_found(monkeypatch):
    _fake_ps(monkeypatch, _ps(
        _row(56964, 1, "11:58",
             f"bfs -S dfs -regextype findutils-default {HOME} -type d -name sustainable-barks"),
        _row(76910, 1, "04:42",
             f"bfs -S dfs -regextype findutils-default {HOME} -type d -name *pareto*"),
    ))
    found = {pid for _, pid, _ in medic._orphaned_scan_procs()}
    assert found == {"56964", "76910"}


def test_a_scan_whose_parent_is_still_alive_is_left_alone(monkeypatch):
    """Somebody is waiting for that output. Not ours to kill."""
    _fake_ps(monkeypatch, _ps(
        _row(56964, 4321, "11:58", f"bfs {HOME} -type d -name sustainable-barks"),
    ))
    assert medic._orphaned_scan_procs() == []


def test_a_scan_inside_a_project_directory_is_left_alone(monkeypatch):
    """Narrow by root as well as by parent: a local search is nobody's problem."""
    _fake_ps(monkeypatch, _ps(
        _row(87190, 1, "02:09",
             "bfs -S dfs . -type f ( -name *.js -o -name *.ts )"),
    ))
    assert medic._orphaned_scan_procs() == []


def test_the_orchestrator_s_own_processes_are_never_reaped(monkeypatch):
    _fake_ps(monkeypatch, _ps(
        _row(111, 1, "40:00", f"python runner.py --find {HOME}"),
        _row(222, 1, "40:00", f"python merge_train.py {HOME}"),
        _row(333, 1, "40:00", f"python resource_medic.py find {HOME}"),
    ))
    assert medic._orphaned_scan_procs() == []


def test_a_young_scan_is_not_reaped(monkeypatch):
    """Found, but under the age limit: it may still be doing something useful."""
    _fake_ps(monkeypatch, _ps(
        _row(56964, 1, "00:30", f"bfs {HOME} -type d -name sustainable-barks"),
    ))
    assert len(medic._orphaned_scan_procs()) == 1
    monkeypatch.setattr(medic, "_children_by_ppid", dict)
    monkeypatch.setattr(medic, "_descendants", lambda pid, kids: [])
    assert medic.reap_orphaned_scans() == 0


def test_an_old_scan_is_reaped_with_its_tree(monkeypatch):
    _fake_ps(monkeypatch, _ps(
        _row(56964, 1, "11:58", f"bfs {HOME} -type d -name sustainable-barks"),
    ))
    monkeypatch.setattr(medic, "_children_by_ppid", dict)
    monkeypatch.setattr(medic, "_descendants", lambda pid, kids: ["56965"])
    killed = []
    monkeypatch.setattr(medic, "journal", lambda *a, **k: None)
    real_sh = medic.sh

    def record(*args, **kwargs):
        if args and args[0] == "kill":
            killed.append(args[-1])

            class R:
                stdout = ""
            return R()
        return real_sh(*args, **kwargs)

    monkeypatch.setattr(medic, "sh", record)
    # re-supply ps through the recording sh
    monkeypatch.setattr(medic, "_orphaned_scan_procs",
                        lambda: [(718, "56964", "bfs ...")])
    assert medic.reap_orphaned_scans() == 1
    assert killed == ["56965", "56964"], "children must die before the parent"


def test_the_reaper_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(medic, "SCAN_ORPHAN_MAX_MIN", 0)
    assert medic.reap_orphaned_scans() == 0


def test_an_unreadable_process_table_is_survivable(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("ps unavailable")

    monkeypatch.setattr(medic, "sh", boom)
    assert medic._orphaned_scan_procs() == []


def test_process_hygiene_calls_the_new_reaper():
    import inspect
    assert "reap_orphaned_scans()" in inspect.getsource(medic.process_hygiene)
