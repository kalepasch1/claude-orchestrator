"""An orphaned build is waste from the second its parent dies, and its child is too.

2026-09-02, this host. `_orphaned_build_procs()` and `reap_orphaned_builds()` already
existed and already worked -- 24 orphaned builds were reaped over the course of the day.
The journal is what showed the two things they got wrong:

    16:08:25Z  reaped-orphan-build  pid=74762 age=30min npm run build
    16:10:32Z  reaped-orphan-build  pid=80494 age=31min node .../build-overlay-2xq0sukr/
                                             node_modules/.bin/nuxt build

Those are one build, reaped twice. `npm run build` is a wrapper; the 5 GB `nuxt build`
is its child. Killing the wrapper reparented the child to launchd, which started its
30-minute clock over -- so the expensive half of the pair outlived the cheap half by
another full window. Every one of today's 24 reaps happened at age 30-33 min, and three
more were alive at 21, 19 and 12 minutes when this was written, holding 439 MB, 5.25 GB
and a --max-old-space-size=16384 heap ceiling between them.

And none of them held a build slot. build_slots limits how many builds a GATE may start;
an orphan's gate is dead, so its flock was released the moment the process died. The
fleet's limit of 2 was therefore enforced against two live gates while up to three
unslotted orphans built beside them -- which is why the limiter looked wired and the
machine still ran four builds. See test_build_slots_everywhere.py for the other half.

30 minutes is the right patience for a build that might be a person's. It is the wrong
patience for one running out of .orch-scratch/build-overlay-*, which no person starts.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import resource_medic  # noqa: E402


class _Reaper:
    """Records `kill -9` calls instead of making them."""

    def __init__(self, ps_out, cwds=None):
        self.ps_out = ps_out
        self.cwds = cwds or {}
        self.killed = []
        self.journal = []

    def sh(self, *args, timeout=60):
        class R:
            stdout = ""
            stderr = ""
            returncode = 0
        r = R()
        if args[0] == "kill":
            self.killed.append(args[-1])
            return r
        if args[0] == "ps":
            fmt = args[2] if len(args) > 2 else ""
            if fmt == "pid=,ppid=":
                rows = []
                for line in self.ps_out.strip().splitlines():
                    f = line.split(None, 3)
                    rows.append("%s %s" % (f[0], f[1]))
                r.stdout = "\n".join(rows)
            else:
                r.stdout = self.ps_out
            return r
        if args[0].endswith("lsof"):
            pid = args[args.index("-p") + 1]
            path = self.cwds.get(str(pid))
            r.stdout = ("n%s\n" % path) if path else ""
            return r
        return r


#: (pid, ppid, etime, command) rows, in `ps -axo pid=,ppid=,etime=,command=` order.
def _ps(rows):
    return "\n".join("%s %s %s %s" % row for row in rows)


@pytest.fixture
def reaper(monkeypatch):
    def _make(rows, cwds=None):
        rp = _Reaper(_ps(rows), cwds)
        monkeypatch.setattr(resource_medic, "sh", rp.sh)
        monkeypatch.setattr(resource_medic, "journal",
                            lambda *a, **k: rp.journal.append(a))
        return rp
    return _make


def test_wrapper_and_its_build_die_together(reaper, monkeypatch):
    """The 16:08/16:10 pair: one build, previously reaped twice."""
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 3)
    rp = reaper([
        ("74762", "1", "31:12", "npm run build"),
        ("80494", "74762",
         "31:05", "node /Users/k/.orch-scratch/build-overlay-2xq0sukr/node_modules/.bin/nuxt build"),
    ])
    assert resource_medic.reap_orphaned_builds() == 1     # one TREE
    assert set(rp.killed) == {"74762", "80494"}, (
        "the 5 GB child survived its wrapper and restarted its own 30-minute clock")


def test_child_is_killed_before_its_parent(reaper, monkeypatch):
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    rp = reaper([
        ("100", "1", "40:00", "npm run build"),
        ("101", "100", "39:00", "node /tmp/x/node_modules/.bin/nuxt build"),
    ])
    resource_medic.reap_orphaned_builds()
    assert rp.killed.index("101") < rp.killed.index("100")


def test_gate_owned_orphan_dies_at_the_short_limit(reaper, monkeypatch):
    """An overlay build cannot belong to a person, so it does not get a person's patience."""
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 3)
    rp = reaper([
        ("200", "1", "05:00",
         "node /Users/k/.orch-scratch/build-overlay-hqt0aoct/node_modules/.bin/nuxt build"),
    ])
    assert resource_medic.reap_orphaned_builds() == 1
    assert rp.killed == ["200"]


def test_a_persons_build_still_gets_the_full_window(reaper, monkeypatch):
    """The narrowness IS the safety argument. Nothing outside the fleet's own scratch
    dirs is reaped early, even when it matches a build marker."""
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 3)
    rp = reaper([("300", "1", "05:00", "npm run dev")], cwds={"300": "/Users/k/Sites/mine"})
    assert resource_medic.reap_orphaned_builds() == 0
    assert rp.killed == []


def test_bare_npm_run_build_is_classified_by_its_cwd(reaper, monkeypatch):
    """Three of today's orphans were bare `npm run build` lines. argv says nothing;
    the overlay is only visible in the cwd."""
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 3)
    rp = reaper([("400", "1", "04:00", "npm run build")],
                cwds={"400": "/Users/k/.orch-scratch/build-overlay-xznf85fc"})
    assert resource_medic.reap_orphaned_builds() == 1
    assert rp.killed == ["400"]


def test_a_parented_build_is_never_touched(reaper, monkeypatch):
    """ppid != 1 means somebody is still waiting on the exit status."""
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 3)
    rp = reaper([
        ("44246", "1", "02:00:00", "python3 runner/merge_train.py"),
        ("500", "44246", "50:00",
         "node /Users/k/.orch-scratch/build-overlay-abc/node_modules/.bin/nuxt build"),
    ])
    assert resource_medic.reap_orphaned_builds() == 0
    assert rp.killed == []


def test_the_runner_is_never_reaped_even_when_parentless(reaper, monkeypatch):
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 1)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 1)
    rp = reaper([("600", "1", "10:00:00",
                  "python3 /Users/k/orch/runner/merge_train.py npm run build")])
    assert rp.killed == [] and resource_medic.reap_orphaned_builds() == 0


def test_disabling_the_gate_clock_falls_back_to_the_long_one(reaper, monkeypatch):
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 0)
    rp = reaper([("700", "1", "05:00",
                  "node /Users/k/.orch-scratch/build-overlay-z/node_modules/.bin/nuxt build")])
    assert resource_medic.reap_orphaned_builds() == 0
    assert rp.killed == []


def test_master_switch_still_disables_everything(reaper, monkeypatch):
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 0)
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_GATE_MAX_MIN", 3)
    rp = reaper([("800", "1", "99:00",
                  "node /Users/k/.orch-scratch/build-overlay-z/node_modules/.bin/nuxt build")])
    assert resource_medic.reap_orphaned_builds() == 0
    assert rp.killed == []


def test_descendant_walk_is_bounded_and_excludes_self():
    kids = {str(i): [str(i + 1)] for i in range(1000)}
    out = resource_medic._descendants(0, kids)
    assert "0" not in out
    assert len(out) <= 200, "an unbounded walk on a pathological table is a hang"


def test_descendant_walk_survives_a_cycle():
    """ps output is a snapshot of a moving table; do not assume it is a tree."""
    kids = {"1": ["2"], "2": ["3"], "3": ["1", "2"]}
    out = resource_medic._descendants(1, kids)
    assert sorted(out) == ["2", "3"]


def test_gate_owned_markers_cover_every_scratch_dir_the_fleet_uses():
    """These are the four shapes seen in today's journal and process table."""
    for cmd in (
        "node /Users/k/.orch-scratch/build-overlay-6h1_n2op/web/node_modules/.bin/nuxt build",
        "node /Users/k/orch/integration-worktrees/abc/node_modules/.bin/nuxt build",
        "node /private/tmp/claude-501/-Users-k-Documents-apparently-law/5dcb/build.mjs",
        "npm run build --prefix /tmp/clean-clone-9xk/web",
    ):
        assert resource_medic._orphan_is_gate_owned("1", cmd), cmd


def test_reap_counts_trees_not_pids(reaper, monkeypatch):
    """The count is journalled and read by an operator; it must not inflate."""
    monkeypatch.setattr(resource_medic, "BUILD_ORPHAN_MAX_MIN", 30)
    rp = reaper([
        ("900", "1", "40:00", "npm run build"),
        ("901", "900", "40:00", "node /tmp/a/node_modules/.bin/nuxt build"),
        ("902", "901", "40:00", "node /tmp/a/node_modules/.bin/vite build"),
    ])
    assert resource_medic.reap_orphaned_builds() == 1
    assert len(rp.killed) == 3
