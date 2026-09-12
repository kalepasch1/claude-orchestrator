"""One machine must stay one host across a macOS rename.

`releases.host` records this single Mac under six names in thirty hours:

    Kales-MacBook-Pro.local  Mac-215.lan  Mac-4.lan
    Mac-39.lan               Mac-172.lan  Mac-213.lan

socket.gethostname() returns the mDNS name, which the network reassigns. Three
fleet-wide decisions are keyed on it:

  * the integration election -- after a rename the same Mac is two live hosts, so
    it can elect its own former name and then refuse to integrate as
    "not the integration owner" (the module's own docstring records what that
    costs: 532 passes, 0 branches considered)
  * the host pause -- kill_switch matched only a `.local` suffix, so a pause
    written under one name stopped applying under the next, and a host an
    operator had stopped came back and resumed writing failed-release rows
  * account partitioning, which reshuffles its shard under a running fleet

Nothing here changes what gets WRITTEN; rows keep using the current name, so
there is no migration. Only MATCHING widens, and both directions of that are
safe: a wider pause match can only stop more work, and folding aliases in the
election can only remove a duplicate of this same machine.
"""
import os

import pytest

import host_identity


# ── the identity itself ───────────────────────────────────────────────────────

def test_the_current_name_is_always_an_alias():
    assert host_identity.current() in host_identity.aliases()


def test_the_stable_name_does_not_carry_a_network_suffix():
    assert not any(host_identity.stable().endswith(s)
                   for s in host_identity.LOCAL_SUFFIXES)


def test_local_suffixes_of_one_name_are_the_same_machine(monkeypatch):
    monkeypatch.setattr(host_identity, "_CACHE", {})
    monkeypatch.setattr(host_identity, "current", lambda: "Mac-215.lan")
    monkeypatch.setattr(host_identity, "_scutil", lambda key: "")
    monkeypatch.setattr(host_identity, "_remembered", set)
    for spelling in ("Mac-215", "Mac-215.lan", "Mac-215.local", "Mac-215.home"):
        assert host_identity.same_machine(spelling), spelling


def test_a_genuinely_different_machine_is_not_folded(monkeypatch):
    """The dangerous direction. Two real Macs must never collapse into one host."""
    monkeypatch.setattr(host_identity, "_CACHE", {})
    monkeypatch.setattr(host_identity, "current", lambda: "Kales-MacBook-Pro.local")
    monkeypatch.setattr(host_identity, "_scutil", lambda key: "")
    monkeypatch.setattr(host_identity, "_remembered", set)
    for other in ("Mandys-MacBook-Pro.local", "Mac-2.powerhub", "Mac-215.lan", ""):
        assert not host_identity.same_machine(other), other


def test_a_remembered_name_is_recognised_after_a_rename(monkeypatch, tmp_path):
    """The whole point: yesterday's name still resolves to this machine today."""
    store = tmp_path / "host-aliases.json"
    monkeypatch.setattr(host_identity, "_store_path", lambda: str(store))
    monkeypatch.setattr(host_identity, "_CACHE", {})
    monkeypatch.setattr(host_identity, "_scutil", lambda key: "Kales-MacBook-Pro")

    monkeypatch.setattr(host_identity, "current", lambda: "Mac-215.lan")
    host_identity.remember()                       # heartbeat under the old name

    monkeypatch.setattr(host_identity, "current", lambda: "Kales-MacBook-Pro.local")
    monkeypatch.setattr(host_identity, "_CACHE", {})
    assert host_identity.same_machine("Mac-215.lan"), \
        "a name this machine used yesterday must still be its own"
    assert host_identity.same_machine("Kales-MacBook-Pro.local")


def test_only_this_process_s_own_name_is_ever_remembered(monkeypatch, tmp_path):
    """The trap the first version fell into, and the reason the rule is absolute.

    remember() used to record whatever the caller passed -- and the caller is the
    heartbeat writer, so one test run put `host-pid-0`, `host1`, `test-host.local`,
    `runner-1.internal` and `Mac.lan` into the live store. `Mac.lan` is a REAL host
    in this fleet's history (691 release rows), and once remembered this machine
    answered same_machine("Mac.lan") with True: it would have folded a different
    machine into itself in the election and absorbed that machine's pause.
    """
    store = tmp_path / "host-aliases.json"
    monkeypatch.setattr(host_identity, "_store_path", lambda: str(store))
    monkeypatch.setattr(host_identity, "_CACHE", {})
    monkeypatch.setattr(host_identity, "_scutil", lambda key: "Kales-MacBook-Pro")
    monkeypatch.setattr(host_identity, "current", lambda: "Kales-MacBook-Pro.local")

    for foreign in ("Mac.lan", "host-pid-0", "test-host.local", "Mandys-MacBook-Pro.local"):
        host_identity.remember(foreign)
        assert not host_identity.same_machine(foreign), \
            f"{foreign} was recorded as this machine's own name"

    host_identity.remember("Kales-MacBook-Pro.local")   # its actual name: accepted
    assert host_identity.same_machine("Kales-MacBook-Pro.local")


def test_the_store_honours_the_test_home_rather_than_live_scratch(monkeypatch, tmp_path):
    """Tests must not be able to write into the fleet's real alias file."""
    monkeypatch.setenv("CLAUDE_ORCH_HOME", str(tmp_path))
    assert host_identity._store_path().startswith(str(tmp_path))


def test_remembering_is_best_effort(monkeypatch):
    """An unwritable store degrades to today's behaviour, never to a wrong answer."""
    monkeypatch.setattr(host_identity, "_store_path", lambda: "/nonexistent/dir/x.json")
    host_identity.remember("whatever")             # must not raise
    assert host_identity.current() in host_identity.aliases()


def test_a_computer_name_with_spaces_matches_its_network_spelling(monkeypatch):
    monkeypatch.setattr(host_identity, "_CACHE", {})
    monkeypatch.setattr(host_identity, "current", lambda: "Kales-MacBook-Pro.local")
    monkeypatch.setattr(host_identity, "_remembered", set)
    monkeypatch.setattr(host_identity, "_scutil",
                        lambda key: "Kale's MacBook Pro" if key == "ComputerName"
                        else "Kales-MacBook-Pro")
    assert "Kales-MacBook-Pro" in host_identity.aliases()


# ── the pause ─────────────────────────────────────────────────────────────────

def test_a_pause_written_under_an_old_name_still_matches(monkeypatch, tmp_path):
    import kill_switch
    store = tmp_path / "host-aliases.json"
    monkeypatch.setattr(host_identity, "_store_path", lambda: str(store))
    monkeypatch.setattr(host_identity, "_CACHE", {})
    monkeypatch.setattr(host_identity, "_scutil", lambda key: "Kales-MacBook-Pro")
    monkeypatch.setattr(host_identity, "current", lambda: "Mac-215.lan")
    host_identity.remember()
    monkeypatch.setattr(host_identity, "current", lambda: "Kales-MacBook-Pro.local")
    monkeypatch.setattr(host_identity, "_CACHE", {})

    assert "Mac-215.lan" in kill_switch._host_aliases()


def test_the_pause_alias_lookup_falls_back_rather_than_raising(monkeypatch):
    import builtins
    import kill_switch
    real_import = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name == "host_identity":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    aliases = kill_switch._host_aliases()
    assert kill_switch.HOST in aliases


# ── the election ──────────────────────────────────────────────────────────────

def _rows(*triples):
    return [{"hostname": h, "code_sha": s, "last_seen": t} for h, s, t in triples]


def test_a_renamed_self_does_not_appear_as_a_second_live_host(monkeypatch):
    import datetime
    import integration_owner as io
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    monkeypatch.setattr(io, "HOST", "Kales-MacBook-Pro.local")
    monkeypatch.setattr(io, "_is_this_machine",
                        lambda n: n in ("Kales-MacBook-Pro.local", "Mac-215.lan"))
    monkeypatch.setattr(io, "_is_behind", lambda a, b: False)
    monkeypatch.setattr(io.db, "select", lambda *a, **k: _rows(
        ("Kales-MacBook-Pro.local", "aaa", now),
        ("Mac-215.lan", "aaa", now),
    ))
    live = io._live_hosts()
    assert list(live) == ["Kales-MacBook-Pro.local"], \
        "one machine under two names must not be two candidates"


def test_another_real_host_is_still_a_separate_candidate(monkeypatch):
    import datetime
    import integration_owner as io
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    monkeypatch.setattr(io, "HOST", "Kales-MacBook-Pro.local")
    monkeypatch.setattr(io, "_is_this_machine", lambda n: n == "Kales-MacBook-Pro.local")
    monkeypatch.setattr(io, "_is_behind", lambda a, b: False)
    monkeypatch.setattr(io.db, "select", lambda *a, **k: _rows(
        ("Kales-MacBook-Pro.local", "aaa", now),
        ("Mandys-MacBook-Pro.local", "bbb", now),
    ))
    assert set(io._live_hosts()) == {"Kales-MacBook-Pro.local", "Mandys-MacBook-Pro.local"}


def test_a_host_is_represented_by_its_newest_code_not_its_newest_row(monkeypatch):
    """Observed live: one hostname, three runners, three different shas.

    Keeping the newest ROW let a machine advertise code older than it actually had,
    and then refuse to integrate under its own stale-code guard.
    """
    import datetime
    import integration_owner as io
    base = datetime.datetime.now(datetime.timezone.utc)
    newest_row = (base - datetime.timedelta(seconds=5)).isoformat()
    older_row = (base - datetime.timedelta(seconds=90)).isoformat()
    monkeypatch.setattr(io, "HOST", "Kales-MacBook-Pro.local")
    monkeypatch.setattr(io, "_is_this_machine", lambda n: n == "Kales-MacBook-Pro.local")
    # "old" is an ancestor of "new"; nothing else is.
    monkeypatch.setattr(io, "_is_behind", lambda a, b: a == "old" and b == "new")
    monkeypatch.setattr(io.db, "select", lambda *a, **k: _rows(
        ("Kales-MacBook-Pro.local", "old", newest_row),   # latest beat, older code
        ("Kales-MacBook-Pro.local", "new", older_row),    # earlier beat, newer code
    ))
    assert io._live_hosts()["Kales-MacBook-Pro.local"] == "new"


def test_a_stale_heartbeat_is_still_excluded(monkeypatch):
    """The freshness rule must survive the folding."""
    import datetime
    import integration_owner as io
    old = (datetime.datetime.now(datetime.timezone.utc)
           - datetime.timedelta(seconds=io.HEARTBEAT_STALE_S + 600)).isoformat()
    monkeypatch.setattr(io, "HOST", "Kales-MacBook-Pro.local")
    monkeypatch.setattr(io, "_is_this_machine", lambda n: n == "Kales-MacBook-Pro.local")
    monkeypatch.setattr(io, "_is_behind", lambda a, b: False)
    monkeypatch.setattr(io.db, "select", lambda *a, **k: _rows(
        ("Mandys-MacBook-Pro.local", "bbb", old),
    ))
    assert io._live_hosts() == {}


def test_an_unreadable_control_plane_still_fails_open(monkeypatch):
    import integration_owner as io

    def boom(*args, **kwargs):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(io.db, "select", boom)
    assert io._live_hosts() == {}
    ok, why = io.decide(local_sha="abc")
    assert ok is True and "fail-open" in why
