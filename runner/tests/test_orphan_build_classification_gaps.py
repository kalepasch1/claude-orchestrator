"""Three ways a dead build stayed invisible to the medic for five and a half days.

AUDITED 2026-09-08 on this host. `_orphaned_build_procs()` returned processes it could
classify, and the machine was simultaneously carrying 30 build processes it could not --
every one started by the orchestrator itself under .orch-scratch/release-qa-overlay-*,
the oldest at 131.8 hours. Running the medic's own predicate against the live process
table is what showed why:

    132.1h  node .../node_modules/.bin/nuxi prepare      orphan: yes   marker: NO
    130.5h  .../@esbuild/darwin-arm64/bin/esbuild ...    orphan: NO    marker: NO
    113.8h  sh -c nuxt prepare || true                   orphan: yes   marker: NO
    113.8h  node .../node_modules/.bin/nuxt prepare      orphan: NO    marker: yes

Three distinct gaps:

  1. NUXI IS NOT NUXT. Nuxt 3 ships its CLI as `nuxi`, so `nuxi prepare` matched neither
     "bin/nuxt" nor any other marker. Seventeen of the thirty.

  2. esbuild's persistent --service child matched nothing on its own.

  3. `sh -c nuxt prepare || true` is parentless but matched no marker -- the list carried
     "nuxt build" and "nuxt dev", never "nuxt prepare" -- so the WHOLE TREE under it was
     unreachable, including the real bin/nuxt build it had spawned. Two such pairs, at
     105.9h and 113.5h.

THE FIX IS THE MARKERS, AND ONLY THE MARKERS. The first attempt also added a walk up the
process tree, so that a build whose parent was itself a dead wrapper counted as
parentless. That was wrong, and test_orphan_build_reaping caught it: reap_orphaned_builds
deliberately reaps and counts TREES, killing a root orphan together with its descendants,
so making the child independently "orphaned" made one tree count as two -- reintroducing
the double-reap that file was written to prevent. Once the root matches a marker, the
existing descendant walk already reaches everything below it. The gap was never the tree
logic; it was that these roots matched no marker.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resource_medic  # noqa: E402

#: ps rows are (pid, ppid, etime, command), matching `ps -axo pid=,ppid=,etime=,command=`.
LONG_ENOUGH_TO_REAP = "31:12"
DAYS_OLD = "5-11:48:00"
EXPECTED_NONE = 0

SCRATCH = "/Users/kpasch/.orch-scratch/release-qa-overlay-79jr5tf2"


class _FakePs:
    def __init__(self, rows):
        self.rows = rows

    def sh(self, *args, timeout=60):
        class Result:
            stdout = ""
            stderr = ""
            returncode = 0
        result = Result()
        if args[0] == "ps":
            result.stdout = "\n".join("%s %s %s %s" % row for row in self.rows)
        return result


@pytest.fixture
def seen(monkeypatch):
    """Return the commands _orphaned_build_procs classifies from a given process table."""
    def _run(rows):
        monkeypatch.setattr(resource_medic, "sh", _FakePs(rows).sh)
        return {command for _secs, _pid, command in resource_medic._orphaned_build_procs()}
    return _run


def test_an_orphaned_nuxi_prepare_is_seen(seen):
    """Gap 1: seventeen of the thirty, invisible because the binary is nuxi, not nuxt."""
    command = f"node {SCRATCH}/node_modules/.bin/nuxi prepare"
    assert command in seen([("94192", "1", DAYS_OLD, command)])


def test_the_root_of_an_esbuild_tree_is_seen(seen):
    """Gap 2. The ROOT is what must be classified; the reaper walks down from there.

    Asserting the esbuild child is itself listed would be asserting the double-reap bug.
    """
    parent = f"node {SCRATCH}/node_modules/.bin/nuxi prepare"
    service = f"{SCRATCH}/node_modules/@esbuild/darwin-arm64/bin/esbuild --service=0.21.5 --ping"
    found = seen([
        ("94192", "1", DAYS_OLD, parent),
        ("4694", "94192", DAYS_OLD, service),
    ])
    assert parent in found, "the orphaned root was not classified"
    assert service not in found, (
        "the child was listed as its own orphan; reap_orphaned_builds counts TREES and "
        "this is how one tree becomes two reaps")


def test_a_parentless_esbuild_is_still_seen_on_its_own(seen):
    """When esbuild IS the root -- its parent already gone -- the marker must carry it."""
    service = f"{SCRATCH}/node_modules/@esbuild/darwin-arm64/bin/esbuild --service=0.21.5 --ping"
    assert service in seen([("4694", "1", DAYS_OLD, service)])


def test_the_shell_wrapper_root_is_seen_so_its_tree_becomes_reachable(seen):
    """Gap 3: the 4.7-day pair.

    Only the wrapper needs classifying. It is the ppid-1 root, and reap_orphaned_builds
    kills its descendants with it -- which is precisely why the child must NOT appear
    here as an orphan in its own right.
    """
    wrapper = "sh -c nuxt prepare || true"
    build = "node /Users/kpasch/Documents/smarter/pasch/node_modules/.bin/nuxt prepare"
    found = seen([
        ("8635", "1", DAYS_OLD, wrapper),
        ("8637", "8635", DAYS_OLD, build),
    ])
    assert wrapper in found, "the parentless wrapper still matches no marker"
    assert build not in found, "the child must be reaped as part of the tree, not counted again"


def test_a_build_under_a_live_gate_is_never_classified_as_an_orphan(seen):
    """THE SAFETY CASE. A build with a live parent has someone waiting on its result."""
    gate = "python runner.py"
    build = f"node {SCRATCH}/node_modules/.bin/nuxi prepare"
    found = seen([
        ("4922", "1", DAYS_OLD, gate),
        ("9001", "4922", LONG_ENOUGH_TO_REAP, build),
    ])
    assert build not in found, "a build with a live parent was classed as an orphan"


def test_a_build_under_an_ordinary_live_process_is_not_an_orphan(seen):
    """Same rule without relying on _NEVER_REAP_MARKERS: any live ppid disqualifies."""
    build = f"node {SCRATCH}/node_modules/.bin/nuxi prepare"
    found = seen([
        ("7000", "1", DAYS_OLD, "/Applications/Some.app/Contents/MacOS/Some"),
        ("9002", "7000", DAYS_OLD, build),
    ])
    assert build not in found


def test_a_malformed_process_table_does_not_hang_or_raise(seen):
    """The medic must never be the thing that breaks. Mutually-referencing ppids."""
    found = seen([
        ("100", "200", DAYS_OLD, "sh -c nuxt prepare || true"),
        ("200", "100", DAYS_OLD, "sh -c nuxi prepare || true"),
    ])
    assert isinstance(found, set)


def test_the_runner_itself_is_never_reaped(seen):
    """_NEVER_REAP_MARKERS still wins, whatever the new markers say."""
    found = seen([("4922", "1", DAYS_OLD, "python runner.py --build")])
    assert len(found) == EXPECTED_NONE


def test_a_young_orphan_is_still_listed_for_the_age_gate_to_judge(seen):
    """This function classifies; reap_orphaned_builds applies the clock. Keep that split."""
    command = f"node {SCRATCH}/node_modules/.bin/nuxi prepare"
    assert command in seen([("94192", "1", "00:45", command)])
