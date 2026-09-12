#!/usr/bin/env python3
"""One machine, one identity — even when macOS renames it.

WHAT THIS MACHINE IS CALLED, OVER 30 HOURS, IN `releases.host`:

    Kales-MacBook-Pro.local   Mac-215.lan   Mac-4.lan
    Mac-39.lan                Mac-172.lan   Mac-213.lan

Six names, one Mac. `socket.gethostname()` on macOS returns the mDNS name, which the
network reassigns on a collision or a DHCP lease change; `scutil --get LocalHostName`
does not move.

WHY THAT IS NOT COSMETIC. Host identity is what three fleet-wide decisions are made of:

  * `integration_owner` elects exactly one host to integrate, from heartbeats keyed by
    hostname. After a rename the same Mac is TWO live hosts for HEARTBEAT_STALE_S -- the
    old name still heartbeating from the row it last wrote, on whatever code it had. The
    machine can elect its own former name and refuse to integrate ("integration owner is
    Mac-215.lan"), or fail the stale-code guard against itself. The module's own docstring
    records what that costs when it happens: 532 merge passes, 0 branches considered.

  * `kill_switch` matches a host pause by name, with aliases that cover only a `.local`
    suffix. A pause written against Mac-215.lan stops applying the moment the machine
    becomes Kales-MacBook-Pro.local -- so a host an operator deliberately stopped comes
    back under a new name and resumes writing failed-release rows, which is precisely the
    poisoning paused_host_guard exists to prevent.

  * `account_partition` / `account_pool` shard work by hostname, so a rename reshuffles
    the shard under a running fleet.

WHAT THIS DOES, AND DELIBERATELY DOES NOT DO.

It does NOT change the name anything writes. Rows keep being written under
`socket.gethostname()`, so there is no migration, nothing to backfill, and no window in
which old rows stop being found. What changes is MATCHING: `aliases()` returns every name
this machine is known to have used, so a lookup keyed on any of them still resolves. That
direction is the safe one -- widening a pause match can only ever stop more work, and
collapsing an election can only ever remove a duplicate of this same machine.

Names are remembered on disk under the scratch root, so a name this Mac used yesterday is
still recognised as its own today. That file is a cache: losing it degrades to exactly
today's behaviour, never to a wrong answer.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

#: Suffixes macOS and the local network attach to the same machine name.
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".localdomain")

_CACHE = {}


def current() -> str:
    """What this machine calls itself right now. This is what gets WRITTEN."""
    try:
        return socket.gethostname() or "unknown"
    except Exception:
        return "unknown"


def stable() -> str:
    """A name for this machine that a DHCP lease cannot change.

    Prefers macOS's LocalHostName, which is set in Sharing preferences and does not
    move when the network renames the mDNS host. Falls back to the bare current name
    with any local suffix stripped -- which is still more stable than the full name,
    because most renames only alter the suffix or the numbering.
    """
    if "stable" in _CACHE:
        return _CACHE["stable"]
    name = _scutil("LocalHostName") or _bare(current())
    _CACHE["stable"] = name or "unknown"
    return _CACHE["stable"]


def aliases() -> set:
    """Every name this machine is known to have used. Never raises, never empty.

    Used for MATCHING only. A pause, a heartbeat or a control row written under any of
    these names belongs to this machine.
    """
    names = set()
    for raw in (current(), stable(), _scutil("LocalHostName"), _scutil("ComputerName")):
        names.update(_variants(raw))
    names.update(_remembered())
    names.discard("")
    return names or {current()}


def same_machine(name) -> bool:
    """True when `name` refers to this machine under any of its names."""
    if not name:
        return False
    candidate = str(name).strip()
    if candidate in aliases():
        return True
    return _bare(candidate) == _bare(stable()) and bool(_bare(candidate))


def remember(name=None) -> None:
    """Record a name THIS PROCESS is currently answering to. Nothing else.

    ONLY `socket.gethostname()` IS EVER RECORDED, and the first version of this
    function is why the rule is absolute. It accepted whatever name the caller
    passed, and the caller is the heartbeat writer -- so within one test run the
    store had absorbed `host-pid-0`, `host1`, `test-host.local`,
    `runner-1.internal` and, worst of all, `Mac.lan`.

    `Mac.lan` is a REAL host in this fleet's history: 691 release rows. Having
    remembered it, this Mac answered same_machine("Mac.lan") with True -- it would
    have folded a genuinely different machine into itself in the integration
    election and absorbed that machine's pause. That is the one direction this
    module must never move in, and a pre-existing heartbeat test caught it.

    So a name enters the store only by being the name this process actually has.
    A caller may pass one, but a mismatch is refused rather than trusted.

    Best-effort by design: the store is a cache, and a machine that cannot write it
    behaves exactly as it did before the cache existed.
    """
    live = current().strip()
    name = (name or live).strip()
    if not name or name != live:
        return
    try:
        path = _store_path()
        if not path:
            return
        known = _read_store(path)
        entry = set(known.get(stable(), []))
        if name in entry:
            return
        entry.add(name)
        known[stable()] = sorted(entry)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(known, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        pass


# ── internals ─────────────────────────────────────────────────────────────────

def _bare(name) -> str:
    """`Mac-215.lan` -> `Mac-215`. The suffix is the part the network owns."""
    name = str(name or "").strip()
    for suffix in LOCAL_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _variants(name) -> set:
    """A name plus the local-suffix spellings of it that mean the same machine."""
    name = str(name or "").strip()
    if not name:
        return set()
    bare = _bare(name)
    out = {name, bare}
    out.update(bare + suffix for suffix in LOCAL_SUFFIXES)
    # ComputerName can carry spaces and a curly apostrophe ("Kale's MacBook Pro");
    # the network form replaces those with hyphens.
    normalised = (bare.replace("’", "").replace("'", "")
                  .replace(" ", "-"))
    if normalised != bare:
        out.add(normalised)
        out.update(normalised + suffix for suffix in LOCAL_SUFFIXES)
    return {n for n in out if n}


def _scutil(key) -> str:
    cache_key = f"scutil:{key}"
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    value = ""
    try:
        result = subprocess.run(["scutil", "--get", key], capture_output=True,
                                text=True, timeout=10)
        if result.returncode == 0:
            value = result.stdout.strip()
    except Exception:
        value = ""
    _CACHE[cache_key] = value
    return value


def _store_path():
    """CLAUDE_ORCH_HOME first, so tests cannot write into the live store.

    94 modules resolve their state from CLAUDE_ORCH_HOME and the suite's conftest
    points it at a temp dir precisely so tests cannot touch live state. Reaching
    for scratch.root() first bypassed that -- which is how a test run put five
    fixture hostnames into the real alias file. Same trap the conftest docstring
    describes for the guard logs, one module over.
    """
    home = os.environ.get("CLAUDE_ORCH_HOME")
    if home:
        try:
            os.makedirs(home, exist_ok=True)
            return os.path.join(home, "host-aliases.json")
        except OSError:
            pass
    try:
        import scratch
        return os.path.join(scratch.root(), "host-aliases.json")
    except Exception:
        return None


def _read_store(path):
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _remembered() -> set:
    path = _store_path()
    if not path:
        return set()
    names = set()
    for name in _read_store(path).get(stable(), []):
        names.update(_variants(name))
    return names


if __name__ == "__main__":
    remember()
    print(f"current  = {current()}")
    print(f"stable   = {stable()}")
    print(f"aliases  = {sorted(aliases())}")
