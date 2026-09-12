#!/usr/bin/env python3
from __future__ import annotations
"""resource_medic.py — autonomous resource-remediation bots for the orchestration layer.

The sentinel reacts (unload a model, kill a zombie, cycle a runner). The MEDIC learns and
PREVENTS: it watches for the recurring RAM / memory / thrash / loop patterns that used to need a
human, and when it sees a pattern REPEAT, it applies a DURABLE root fix (fleet-wide config) so the
issue stops happening at all — then files an ops card telling Macey what it changed (informing,
not asking).

Bots (each: detect -> remediate -> journal -> escalate-if-durable):

  memory_guard   Predictive OOM prevention. Uses the authoritative macOS memory_pressure signal
                 (not raw free pages). Graduated: warn -> unload heaviest local model + clamp
                 throttle; critical -> also reap the oldest agent. Never waits for OOM.
  thrash_hunter  Reads the medic+sentinel event journals. If any remediation class fires >=
                 THRESHOLD times in a window, applies the DURABLE fix:
                   • model reload/clamp thrash -> permanently canary-exclude that model
                     (ORCH_CANARY_ONLY_OLLAMA_MODELS via fleet_config)
                   • restart storm            -> reduce MAX_PARALLEL fleet-wide (over-subscribed)
                   • dedupe recurrence        -> already guarded at db.insert; escalate w/ source
  process_hygiene Reap multi-hour agent zombies, orphaned llama-servers, oversized logs.
  loop_breaker   Detect global-pause / restart oscillation and hold a stable state.

Everything is fail-soft: a medic bug must never take the fleet down. Durable changes go through
fleet_control's fleet_config (safe keys only) so BOTH Macs converge. Journals to
.runtime/medic.jsonl; escalations to the approvals table (kind='self', informational).
"""
import datetime
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
REPO = os.path.dirname(HERE)
RUNTIME = os.path.join(REPO, ".runtime")
JOURNAL = os.path.join(RUNTIME, "medic.jsonl")
STATE = os.path.join(RUNTIME, "medic_state.json")
SENTINEL_LOG = os.path.join(RUNTIME, "sentinel.log")

# thresholds (env-tunable)
THRASH_WINDOW_MIN = int(os.environ.get("MEDIC_THRASH_WINDOW_MIN", "60"))
MODEL_CLAMP_THRASH_N = int(os.environ.get("MEDIC_MODEL_CLAMP_N", "4"))
RESTART_STORM_N = int(os.environ.get("MEDIC_RESTART_STORM_N", "6"))
AGENT_MAX_MIN = int(os.environ.get("MEDIC_AGENT_MAX_MIN", "150"))
LOG_CAP_MB = int(os.environ.get("MEDIC_LOG_CAP_MB", "20"))
#: Minutes an ORPHANED build/test process may outlive its spawner before the medic
#: kills it. 30, not 150: the gates' own ceiling is MERGE_TRAIN_TEST_TIMEOUT (900s),
#: so a build that has been parentless for half an hour is past any budget that could
#: still have used its exit status. Set MEDIC_BUILD_ORPHAN_MAX_MIN=0 to disable.
BUILD_ORPHAN_MAX_MIN = int(os.environ.get("MEDIC_BUILD_ORPHAN_MAX_MIN", "30"))
#: The same clock, for orphans the ORCHESTRATOR itself unmistakably started: a build
#: running out of .orch-scratch/build-overlay-*, an integration worktree, or a
#: /private/tmp/claude-* checkout. 30 minutes is the right patience for a build that
#: MIGHT be a person's, and far too much for one that cannot be. Measured 2026-09-02:
#: 24 orphaned builds reaped in a single day, every one of them at age 30-33 min, and
#: none of them holding a build slot -- so the fleet's limit of 2 was being enforced
#: against 2 live gates while up to three unslotted orphans built alongside them. One
#: carried 5.2 GB RSS on a machine whose swap was 87% used. Set to 0 to fall back to
#: BUILD_ORPHAN_MAX_MIN for these too.
BUILD_ORPHAN_GATE_MAX_MIN = int(os.environ.get("MEDIC_BUILD_ORPHAN_GATE_MAX_MIN", "3"))
PRESSURE_WARN = int(os.environ.get("MEDIC_PRESSURE_WARN_PCT", "25"))   # free% below this = warn
PRESSURE_CRIT = int(os.environ.get("MEDIC_PRESSURE_CRIT_PCT", "12"))   # free% below this = critical
#: Sustained page-out rate that means the machine is EVICTING, not merely busy.
#:
#: 200 rather than 1, because a short burst when a large build starts is normal and
#: self-correcting; and 200 rather than 5,000, because the healthy baseline is not
#: "low", it is ZERO. Measured 2026-09-08 across ten consecutive 15-second samples on
#: this host while it was healthy: swapouts/s was 0 in every single one, while swapins
#: ranged 2-863/s and memory_pressure reported 81-83% free. 200 pages/s is roughly
#: 800 KB/s of sustained eviction -- unmissable against a zero floor, and well clear of
#: any single build's startup transient.
SWAPOUT_THRASH_PPS = int(os.environ.get("MEDIC_SWAPOUT_THRASH_PPS", "200"))
#: How long a memory-pressure EPISODE stays on the record when deciding whether pressure
#: is recurring. See memory_guard: the old consecutive-cycle streak could not survive the
#: guard's own success, so the durable fix behind it was unreachable.
MEM_EPISODE_WINDOW_H = float(os.environ.get("MEDIC_MEM_EPISODE_WINDOW_H", "24"))
#: Episodes inside that window before the lane ceiling is lowered durably. Five, matching
#: the streak length this replaces. Measured: 15 episodes between 2026-09-06 and 09-08
#: would have escalated on the fifth instead of never.
MEM_EPISODES_BEFORE_DURABLE = int(os.environ.get("MEDIC_MEM_EPISODES_BEFORE_DURABLE", "5"))


def _now():
    """Return current UTC time. Uses timezone-aware constructor (utcnow is deprecated >=3.12)."""
    return datetime.datetime.now(datetime.timezone.utc)


def journal(bot, action, detail="", durable=False):
    ts = _now().isoformat().replace("+00:00", "Z")  # compact UTC suffix
    row = {"at": ts, "bot": bot, "action": action,
           "detail": str(detail)[:300], "durable": bool(durable)}
    print(f"medic[{bot}] {action} {str(detail)[:120]}", flush=True)
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        with open(JOURNAL, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {}


def save_state(st):
    try:
        os.makedirs(RUNTIME, exist_ok=True)
        json.dump(st, open(STATE, "w"), indent=1)
    except OSError:
        pass


def sh(*args, timeout=60):
    return subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)


def _set_fleet_config(key, value):
    """Durable, fleet-wide (both Macs) via the config gateway. Safe keys only."""
    try:
        import db
        db.insert("fleet_config", {"key": key, "value": str(value)}, upsert=True)
        return True
    except Exception:
        return False


def _escalate(title, why, value):
    try:
        import db
        db.insert("approvals", {"project": "ORCHESTRATOR", "kind": "self",
                                "title": title[:120], "why": why[:400], "value": value[:200],
                                "risk": "Auto-applied by resource_medic; informational."})
    except Exception:
        pass


# ── authoritative memory signal (macOS) ───────────────────────────────────────

def memory_free_pct():
    """macOS memory_pressure 'System-wide memory free percentage' — the OS's own authoritative
    signal, immune to the raw-Pages-free misread that caused earlier false clamps. Returns int %
    or None off-macOS."""
    try:
        out = sh("memory_pressure", timeout=15).stdout
        import re
        m = re.search(r"free percentage:\s*(\d+)%", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None


def _swapouts_total():
    """Cumulative pages evicted to swap since boot, or None where unavailable."""
    try:
        out = sh("vm_stat", timeout=15).stdout
        for line in out.splitlines():
            if line.startswith("Swapouts"):
                return int(line.rsplit(None, 1)[-1].strip().rstrip("."))
    except Exception:
        return None
    return None


def swapout_rate_pps(st):
    """Pages per second being evicted to swap since the last call. None on first call.

    A SUPPLEMENT TO memory_free_pct, NOT A REPLACEMENT -- AND THE COMMIT THAT ADDED IT
    SAID OTHERWISE, WRONGLY.

    d5dd1105 claimed memory_guard "existed through the entire crisis and never ran once".
    That is false, and the journal says so plainly: the guard fired 15 times between
    2026-09-06 and 09-08, at free percentages of 16 to 24. The claim came from a single
    memory_pressure reading of 67% taken at one moment and reasoned from, instead of a
    grep of .runtime/medic.jsonl. Corrected here so nobody inherits it.

    What is true is narrower and still worth acting on: the percentage counts
    compressible and reclaimable pages as free, so it CAN sit well above the 25% warn
    line while the machine is evicting hard. The 67% reading was real, taken while the
    host had 3.62 GB free, 44 GB of swap in use and a load average of 55 with only 14 of
    772 processes runnable. On that cycle the guard would not have fired, and swapouts
    would have caught it. That is the gap this closes -- one blind spot, not a dead guard.

    The percentage is not a bad number, it is the wrong question: macOS counts
    compressible and reclaimable pages as free, so it stays high precisely when the
    machine is working hardest to keep it high. Eviction is the thing that hurts, and
    eviction has its own counter.

    Swapins were considered and rejected as the signal. They fire during ordinary
    recovery -- a process touching a page evicted hours ago faults it back, which is
    normal -- and the same ten healthy samples showed 2 to 863 swapins/s while swapouts
    stayed at 0. Swapins measure the past; swapouts measure now.
    """
    now = time.time()
    total = _swapouts_total()
    previous_total = st.get("swapouts_total")
    previous_at = st.get("swapouts_at")
    if total is not None:
        st["swapouts_total"] = total
        st["swapouts_at"] = now
    if total is None or previous_total is None or previous_at is None:
        return None
    elapsed = now - previous_at
    if elapsed <= 0 or total < previous_total:
        return None                      # clock skew, or the counter wrapped/rebooted
    return (total - previous_total) / elapsed


def _recent_episodes(st, record=False):
    """Timestamps of memory-pressure episodes still inside MEM_EPISODE_WINDOW_H.

    Replaces a consecutive-cycle streak that the guard's own success always reset. See
    the long note in memory_guard for the evidence; the short version is that unloading a
    16 GB model recovers free% by design, so a counter that resets on recovery can only
    ever reach one.
    """
    now = time.time()
    cutoff = now - MEM_EPISODE_WINDOW_H * 3600
    episodes = [at for at in (st.get("mem_episodes") or []) if at >= cutoff]
    if record:
        episodes.append(now)
    return episodes


# ── BOT 1: memory_guard (predictive OOM prevention) ───────────────────────────

def memory_guard(st):
    free = memory_free_pct()
    # TWO SIGNALS, BECAUSE EITHER CAN MISS A CYCLE THE OTHER CATCHES.
    #
    # free% is the OS's own summary and is right about outright exhaustion -- it fired
    # 15 times over three days in September at 16-24% free, so it works. It can also sit
    # at 67% while the box has 3.62 GB free and a load of 55 spent paging, because it
    # counts compressible pages as free. swapout_rate_pps sees eviction directly and its
    # healthy baseline is measured at exactly zero. Either one is enough to act on;
    # requiring both would reintroduce the blind spot.
    evicting = swapout_rate_pps(st)
    thrashing = evicting is not None and evicting >= SWAPOUT_THRASH_PPS
    if free is None and not thrashing:
        return
    if (free is None or free >= PRESSURE_WARN) and not thrashing:
        # NOTE WHAT IS NOT HERE: a reset of the episode record.
        #
        # This used to be `st["mem_warn_streak"] = 0`, and that single line made the
        # durable fix below unreachable. The streak counted CONSECUTIVE cycles under the
        # threshold, and the guard's own first action -- unloading a 16-23 GB model --
        # reliably pushes free% back above it. So the next cycle recovered, the streak
        # reset to zero, ollama reloaded the model on the next request, and the pressure
        # returned. The journal is unambiguous: 15 `unloaded-model` rows between
        # 2026-09-06 and 09-08, and not one `durable-lower-lanes`. Fifteen interventions,
        # zero durable fixes, on a box that sat at 44 GB of swap throughout.
        #
        # Recurrence is the thing the durable fix cares about, and recurrence is measured
        # over time, not over consecutive samples. Episodes age out of the window on their
        # own; a genuinely healthy fleet empties the record without needing this reset.
        return
    if free is None or free >= PRESSURE_WARN:
        level = "warn"                   # thrashing, but not yet starved
        journal("memory_guard", "thrashing",
                f"swapouts {evicting:.0f}/s (threshold {SWAPOUT_THRASH_PPS}/s) while "
                f"memory_pressure reports {free}% free -- the percentage cannot see this")
    else:
        level = "critical" if free < PRESSURE_CRIT else "warn"
    st["mem_episodes"] = _recent_episodes(st, record=True)
    # 1) unload the heaviest loaded local model (biggest instant win)
    unloaded = _unload_heaviest_model()
    if unloaded:
        journal("memory_guard", "unloaded-model", f"{unloaded} at free={free}% ({level})")
    # 2) clamp the throttle so no new heavy claims pile on
    try:
        import resource_governor as g
        g.set_throttle(1 if level == "critical" else max(1, g.current_limit() // 2))
    except Exception:
        pass
    # 3) critical: also reap the oldest long-running agent to guarantee headroom
    if level == "critical":
        reaped = _reap_oldest_agent()
        if reaped:
            journal("memory_guard", "reaped-agent-critical", reaped)
    # 4) recurring memory warns => the sustained-load cap is too high for this box: lower it durably
    if len(st.get("mem_episodes") or []) >= MEM_EPISODES_BEFORE_DURABLE:
        try:
            cur = int(os.environ.get("MAX_PARALLEL", "10"))
            new = max(4, cur - 2)
            if new < cur and _set_fleet_config("MAX_PARALLEL", new):
                _set_fleet_config("MAX_PARALLEL_CEILING", new)
                journal("memory_guard", "durable-lower-lanes", f"MAX_PARALLEL {cur}->{new} (sustained mem pressure)", durable=True)
                _escalate(f"Lanes lowered to {new} (sustained memory pressure)",
                          f"{len(st['mem_episodes'])} memory-pressure episodes in "
                          f"{MEM_EPISODE_WINDOW_H:.0f}h at {cur} lanes.",
                          "Prevents OOM/restart thrash; raise later if RAM added.")
                st["mem_episodes"] = []
        except Exception:
            pass


#: `ollama ps` prints SIZE as a number and a unit in SEPARATE columns. Multipliers to GB.
_MODEL_SIZE_UNITS = {"KB": 1.0 / (1024 * 1024), "MB": 1.0 / 1024, "GB": 1.0, "TB": 1024.0}


def _loaded_models():
    """[(gb, name)] of currently loaded ollama models, biggest first.

    THE UNIT COLUMN IS A SEPARATE COLUMN, AND IGNORING IT INVERTED THE RANKING.

    `ollama ps` prints:

        NAME                       ID              SIZE      PROCESSOR   CONTEXT  UNTIL
        nomic-embed-text:latest    0a109f422b47    370 MB    100% GPU    2048     4 minutes...

    so p[2] is "370" and p[3] is "MB". This read float(p[2]) as gigabytes, which turned a
    370 MB embedding model into a 370 GB one -- larger than anything real. Since the list
    is sorted biggest-first and _unload_heaviest_model takes models[0], the guard then
    unloaded the SMALLEST model on the box while a genuine 16 GB one sat untouched, and
    journalled it as a success. It is in the record twice:

        2026-09-07T05:35:27  unloaded-model  nomic-embed-text:latest (370.0GB) at free=20%
        2026-09-07T05:38:11  unloaded-model  nomic-embed-text:latest (370.0GB) at free=18%

    Two interventions three minutes apart, each freeing 370 MB and reporting 370 GB. The
    second one happened because the first could not have helped.

    It also defeated the MEDIC_UNLOAD_MIN_GB=8 floor, which exists to stop the guard
    thrashing small models: 370 clears 8 comfortably when the units are wrong.
    """
    out = []
    try:
        for line in sh("ollama", "ps", timeout=20).stdout.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                magnitude = float(parts[2])
            except ValueError:
                continue
            multiplier = _MODEL_SIZE_UNITS.get(parts[3].upper())
            if multiplier is None:
                continue          # an unknown unit is not a number we may guess at
            out.append((magnitude * multiplier, parts[0]))
    except Exception:
        pass
    out.sort(reverse=True)
    return out


def _unload_heaviest_model():
    models = _loaded_models()
    if models and models[0][0] >= float(os.environ.get("MEDIC_UNLOAD_MIN_GB", "8")):
        name = models[0][1]
        try:
            sh("ollama", "stop", name, timeout=90)
            return f"{name} ({models[0][0]}GB)"
        except Exception:
            return None
    return None


def _etime_seconds(text):
    """Parse ps `etime` — [[DD-]HH:]MM:SS — into seconds. None when unparseable.

    NOT `etimes`. That keyword is procps (Linux) only; BSD ps, which is what macOS
    ships, answers `ps: etimes: keyword not found` on stderr, returns 1, and then
    prints the row anyway WITHOUT that column. So the caller gets well-formed output
    with one field missing, every row fails its field-count check, and the loop
    silently sees an empty process table. Nothing errors and nothing is ever reaped.
    Measured 2026-09-02: `_agent_procs()` returned [] on a Mac with 771 processes.
    """
    t = (text or "").strip()
    if not t:
        return None
    days = 0
    if "-" in t:
        d, _, t = t.partition("-")
        try:
            days = int(d)
        except ValueError:
            return None
    bits = t.split(":")
    try:
        bits = [int(b) for b in bits]
    except ValueError:
        return None
    if len(bits) == 2:
        h, m, s = 0, bits[0], bits[1]
    elif len(bits) == 3:
        h, m, s = bits
    else:
        return None
    return days * 86400 + h * 3600 + m * 60 + s


def _agent_procs():
    """[(secs, pid, cmd)] of coding-agent processes (not the fleet's python/ollama server)."""
    res = []
    try:
        for line in sh("ps", "-axo", "pid=,etime=,command=", timeout=20).stdout.splitlines():
            parts = line.strip().split(None, 2)
            if len(parts) < 3:
                continue
            pid, et, cmd = parts
            et = _etime_seconds(et)
            if et is None:
                continue
            low = cmd.lower()
            if any(t in low for t in ("/gemini", "bin/gemini", "aider", "codex exec", "claude exec", " grok")) \
               and "runner.py" not in low and "sentinel.py" not in low \
               and "resource_medic" not in low and "ollama serve" not in low:
                try:
                    res.append((int(et), pid, cmd))
                except ValueError:
                    continue
    except Exception:
        pass
    res.sort(reverse=True)
    return res


#: Command signatures of the build/test tools the gates spawn. Matched against the
#: lowercased command line. Deliberately narrow: this list is the whole safety
#: argument for killing by pattern, so it names tools, not the word "node".
_BUILD_TOOL_MARKERS = (
    "nuxt build", "nuxt dev", "nuxt.mjs build", "nuxt.mjs dev", "bin/nuxt",
    # NUXI IS NUXT'S CLI BINARY, AND ITS ABSENCE HERE COST FIVE AND A HALF DAYS.
    #
    # Nuxt 3 ships its command line as `nuxi`, so a gate that runs `nuxi prepare`
    # produces `node .../node_modules/.bin/nuxi prepare` -- which matches "bin/nuxt"
    # nowhere, because the binary is not called nuxt. Audited 2026-09-08: this machine
    # was carrying 30 build processes the medic could not see, the oldest at 131.8
    # hours, EVERY one of them started by the orchestrator itself under
    # .orch-scratch/release-qa-overlay-*. Seventeen were `nuxi prepare`.
    "bin/nuxi", "nuxi prepare", "nuxi build", "nuxi dev",
    # `prepare` for the nuxt spelling too. The list covered build and dev and stopped
    # there, but prepare is a gate step like any other and hangs like any other.
    "nuxt prepare",
    # esbuild's persistent service. It is spawned as a long-lived child of a bundler
    # and exits when its parent does -- so when the parent is an unreapable orphan, the
    # service outlives it too. Six of the thirty were these, at up to 130.2 hours.
    "esbuild --service", "bin/esbuild",
    "vite build", "vite dev", "next build", "next dev",
    "vitest", "jest", "playwright test", "cypress run",
    "npm run build", "npm run dev", "npm run test", "npm run lint", "npm test",
    "pnpm run build", "pnpm run dev", "pnpm run test", "pnpm build", "pnpm test",
    "yarn build", "yarn dev", "yarn test",
    "-m pytest", "bin/pytest", "tsc --noemit", "tsc -p",
)

#: Never reap these, whatever else matches. The runner and its own periodic jobs are
#: long-lived by design, and the medic must never kill the thing that runs the medic.
_NEVER_REAP_MARKERS = (
    "runner.py", "sentinel.py", "resource_medic", "keepalive.sh",
    "merge_train.py", "release_train.py", "claudeRunner".lower(),
)


def _orphaned_build_procs():
    """[(secs, pid, cmd)] of parentless build/test processes.

    ppid == 1 is the whole point. A build the gates started has a live parent that is
    waiting on its exit status; once that parent is gone the process has been reparented
    to launchd and NOTHING can ever read its result. It is pure load. On 2026-09-01 this
    machine was carrying twelve of them — a `nuxt run dev:full` at 12h53m and 415% CPU,
    two `nuxt build`s inside _ARCHIVED-apparently-do-not-use, a `pnpm run build:vercel`
    at 4h58m — and sat at a 1-minute load average of 59. Every test verdict the merge
    train produced in that state is suspect, and production_push_guard's load cool-down
    (threshold: cores x 0.5) could never settle, so every red suite it saw cost the full
    180s wait before a re-run that was just as contended.
    """
    res = []
    try:
        # `etime`, NOT `etimes` — see _etime_seconds. The first version of this
        # function asked for `etimes` and was therefore blind: BSD ps drops the
        # unknown column, every row came back one field short, and the loop below
        # skipped all 771 of them. It reported zero orphans on a machine that had
        # twelve.
        out = sh("ps", "-axo", "pid=,ppid=,etime=,command=", timeout=20).stdout
    except Exception:
        return res
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, et, cmd = parts
        et = _etime_seconds(et)
        if et is None:
            continue
        if ppid != "1":
            continue                      # still has a parent that can use the result
        low = cmd.lower()

        if any(m in low for m in _NEVER_REAP_MARKERS):
            continue
        if not any(m in low for m in _BUILD_TOOL_MARKERS):
            continue
        try:
            secs = int(et)
            if int(pid) <= 1 or int(pid) == os.getpid():
                continue
        except ValueError:
            continue
        res.append((secs, pid, cmd))
    res.sort(reverse=True)
    return res


#: Path fragments that only the orchestrator produces. A process running out of one of
#: these was started by a gate, never by a person at a shell, so once it is parentless
#: there is nobody left who could read its exit status -- not in 30 minutes, not ever.
_GATE_OWNED_PATHS = (
    # Both spellings: the scratch root moved to `.orch-scratch.noindex` so macOS stops
    # indexing it, and a process started before that change still has overlays under
    # the old name. Matching only the new one would leave those orphans unreaped.
    "/.orch-scratch/", "/.orch-scratch.noindex/", "build-overlay-",
    "integration-worktrees/",
    "/private/tmp/claude-", "clean-clone-",
)


def _proc_cwd(pid):
    """Working directory of a pid, or "" when it cannot be read.

    `npm run build` says nothing about WHERE it is building: three of today's orphans
    were bare `npm run build` lines whose overlay only shows up in their child's argv
    or in their own cwd. Called for a handful of already-matched candidates, never for
    the whole process table.
    """
    try:
        out = sh("/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn",
                 timeout=10).stdout
    except Exception:
        return ""
    for line in out.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def _children_by_ppid():
    """{ppid: [pid, ...]} for the whole process table. {} when ps fails."""
    kids = {}
    try:
        out = sh("ps", "-axo", "pid=,ppid=", timeout=20).stdout
    except Exception:
        return kids
    for line in out.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        kids.setdefault(parts[1], []).append(parts[0])
    return kids


def _descendants(pid, kids):
    """Every pid below `pid`, breadth-first. Bounded; never includes `pid` itself."""
    out, queue, seen = [], list(kids.get(str(pid), [])), {str(pid)}
    while queue and len(out) < 200:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        out.append(cur)
        queue.extend(kids.get(cur, []))
    return out


def _orphan_is_gate_owned(pid, cmd):
    """True when this parentless build can only have come from a gate."""
    low = (cmd or "").lower()
    if any(m in low for m in _GATE_OWNED_PATHS):
        return True
    cwd = _proc_cwd(pid).lower()
    return bool(cwd) and any(m in cwd for m in _GATE_OWNED_PATHS)


def reap_orphaned_builds():
    """Kill parentless build/test processes and everything under them.

    Two things changed here on 2026-09-02, both from the same day's measurements.

    1. THE TREE, NOT THE PROCESS. `npm run build` spawns the real `nuxt build` as its
       child. Killing only the wrapper left the 5 GB node process alive with a fresh
       ppid of 1, so it waited out the FULL window a second time before its own turn
       came. Today's journal shows exactly that shape: pid=74762 `npm run build` reaped
       at 16:08, pid=80494 its overlay build reaped at 16:10 -- and pairs like it all
       day. Reaping the descendants with the parent halves the waste per orphan and
       removes the second window entirely.

    2. A SHORTER CLOCK FOR BUILDS THE FLEET OWNS. See BUILD_ORPHAN_GATE_MAX_MIN.

    Returns the number of process TREES reaped (not pids), so the count still means
    "orphans dealt with".
    """
    if BUILD_ORPHAN_MAX_MIN <= 0:
        return 0
    killed = 0
    kids = _children_by_ppid()
    for secs, pid, cmd in _orphaned_build_procs():
        gate_owned = _orphan_is_gate_owned(pid, cmd)
        limit = BUILD_ORPHAN_MAX_MIN
        if gate_owned and BUILD_ORPHAN_GATE_MAX_MIN > 0:
            limit = min(limit, BUILD_ORPHAN_GATE_MAX_MIN)
        if secs < limit * 60:
            continue
        tree = _descendants(pid, kids)
        # Children first: killing the wrapper first can let a shell respawn or let the
        # child reparent before we get to it.
        for child in reversed(tree):
            sh("kill", "-9", child)
        sh("kill", "-9", pid)
        journal("process_hygiene", "reaped-orphan-build",
                f"pid={pid} age={secs // 60}min limit={limit}min "
                f"{'gate-owned ' if gate_owned else ''}"
                f"+{len(tree)} descendant(s) {cmd[:80]}")
        killed += 1
    return killed


#: Search tools an agent shell reaches for when it does not know where a repo lives.
_SCAN_TOOL_MARKERS = ("bfs ", "find ", "fd ", "mdfind ")

#: A scan is only reapable if it is rooted somewhere broad enough that it can run for
#: minutes. A scan of a project directory is nobody's problem and is left alone.
_BROAD_SCAN_ROOTS = (os.path.expanduser("~"), "/Users/", "/Volumes/", " / ")

#: Minutes a parentless home-directory scan may burn a core before it is reaped.
SCAN_ORPHAN_MAX_MIN = float(os.environ.get("ORCH_SCAN_ORPHAN_MAX_MIN", "3"))


def _orphaned_scan_procs():
    """[(secs, pid, cmd)] of parentless filesystem scans rooted at a broad path.

    MEASURED 2026-09-03. Load average 67 on this Mac, and merge_train's own CPU clamp
    reacting to it exactly as designed:

        merge_train: load/core 7.69 (soft 1.5 hard 3.0) — running 1 project worker(s)
                     instead of 4

    Two of the top four CPU consumers were these:

        bfs -S dfs ... /Users/kpasch -type d -name sustainable-barks   11m58s, 82.6%
        bfs -S dfs ... /Users/kpasch -type d -name *pareto*             4m42s, 68.1%

    Both ppid 1, both descendants of `/bin/zsh -c source ~/.claude/shell-snapshots/...`
    -- agent sessions that had already exited. An agent that does not know where a repo
    lives searches the whole home directory for it; when the session ends the search is
    reparented to launchd and NOTHING can ever read its output. Killing the first one
    took the load average from 67 to 31 within a minute.

    This is not a cosmetic tidy-up. Load is what the governor clamps merge workers on,
    so a parentless scan nobody will ever read the result of directly throttles the
    fleet's real throughput -- and it makes every test verdict produced in that state
    suspect, which is the same argument reap_orphaned_builds already makes.

    Deliberately narrow: ppid 1 AND a scan tool AND a broad root AND older than
    SCAN_ORPHAN_MAX_MIN. A scan inside a project directory, or one whose parent is
    still alive and waiting for it, is left entirely alone.
    """
    res = []
    try:
        out = sh("ps", "-axo", "pid=,ppid=,etime=,command=", timeout=20).stdout
    except Exception:
        return res
    for line in out.splitlines():
        parts = line.strip().split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, et, cmd = parts
        if ppid != "1":
            continue
        secs = _etime_seconds(et)
        if secs is None:
            continue
        low = cmd.lower()
        if any(m in low for m in _NEVER_REAP_MARKERS):
            continue
        if not any(m in low for m in _SCAN_TOOL_MARKERS):
            continue
        if not any(root.lower() in low for root in _BROAD_SCAN_ROOTS):
            continue
        try:
            if int(pid) <= 1 or int(pid) == os.getpid():
                continue
        except ValueError:
            continue
        res.append((int(secs), pid, cmd))
    res.sort(reverse=True)
    return res


def reap_orphaned_scans():
    """Kill parentless home-directory scans and their trees. Returns trees reaped."""
    if SCAN_ORPHAN_MAX_MIN <= 0:
        return 0
    killed = 0
    kids = _children_by_ppid()
    for secs, pid, cmd in _orphaned_scan_procs():
        if secs < SCAN_ORPHAN_MAX_MIN * 60:
            continue
        tree = _descendants(pid, kids)
        for child in reversed(tree):
            sh("kill", "-9", child)
        sh("kill", "-9", pid)
        journal("process_hygiene", "reaped-orphan-scan",
                f"pid={pid} age={secs // 60}min limit={SCAN_ORPHAN_MAX_MIN}min "
                f"+{len(tree)} descendant(s) {cmd[:80]}")
        killed += 1
    return killed


def _reap_oldest_agent():
    procs = _agent_procs()
    if procs:
        secs, pid, cmd = procs[0]
        sh("kill", "-9", pid)
        return f"pid={pid} age={secs // 60}min {cmd[:50]}"
    return None


# ── BOT 2: thrash_hunter (durable root fixes on recurrence) ───────────────────

def _parse_ts(text):
    """Parse one of our own UTC timestamps into an AWARE datetime, or None.

    Every writer in the fleet stamps UTC and marks it with a trailing "Z": journal() above
    does `_now().isoformat().replace("+00:00", "Z")`, and sentinel.py does
    `datetime.datetime.utcnow().isoformat() + "Z"` — the second of which is a NAIVE clock
    reading with a UTC marker glued on. Reading either one back has to produce something
    comparable to _now(), which is aware.

    That is the whole of the bug this helper exists to remove: _recent_events() used to strip
    the "Z" off the sentinel timestamp and compare the resulting NAIVE datetime against an
    AWARE cutoff. Python does not order those — it raises
    "TypeError: can't compare offset-naive and offset-aware datetimes" — and the comparison
    sat inside a bare `except Exception: pass`, so there was no traceback and no log line.
    Every sentinel event was silently dropped from every window, which meant thrash_hunter()
    and loop_breaker() never saw a single ram-clamp, dedupe, runner-cycled or runner-wedged
    event: the two bots whose entire job is spotting repetition were counting nothing but the
    medic's own journal, forever.

    A timestamp that arrives with no offset is assumed UTC, because that is what our writers
    mean by it.
    """
    try:
        t = datetime.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        return t.replace(tzinfo=datetime.timezone.utc)
    return t


def _recent_events(minutes):
    """Merge medic journal + sentinel log lines within the window."""
    cutoff = _now() - datetime.timedelta(minutes=minutes)
    events = []
    # medic journal
    try:
        for line in open(JOURNAL):
            try:
                r = json.loads(line)
                t = _parse_ts(r["at"])
                if t is not None and t >= cutoff:
                    events.append((r.get("bot", ""), r.get("action", ""), r.get("detail", "")))
            except Exception:
                continue
    except OSError:
        pass
    # sentinel log (ram-clamp / dedupe / runner-cycled / extra-keepalive-killed)
    try:
        for line in open(SENTINEL_LOG):
            for tag in ("ram-clamp", "dedupe", "runner-cycled", "runner-wedged",
                        "extra-keepalive-killed", "zombie-agent-reaped"):
                if tag in line:
                    t = _parse_ts(line.split(" ", 1)[0])
                    if t is not None and t >= cutoff:
                        events.append(("sentinel", tag, line.strip()[-120:]))
    except OSError:
        pass
    return events


def thrash_hunter(st):
    ev = _recent_events(THRASH_WINDOW_MIN)
    import collections, re
    counts = collections.Counter(a for _b, a, _d in ev)

    # (a) model reload/clamp thrash -> permanently canary-exclude the offending model(s)
    clamp_events = [d for b, a, d in ev if a in ("ram-clamp", "unloaded-model")]
    if len(clamp_events) >= MODEL_CLAMP_THRASH_N:
        models = set(re.findall(r"([\w./:-]+:\d+\w*|[\w./-]+:latest)", " ".join(clamp_events)))
        already = set(os.environ.get("ORCH_CANARY_ONLY_OLLAMA_MODELS", "").split(","))
        newbl = sorted(m for m in models if m and m not in already)
        if newbl:
            merged = ",".join(sorted(x for x in already | set(newbl) if x))
            if _set_fleet_config("ORCH_CANARY_ONLY_OLLAMA_MODELS", merged):
                journal("thrash_hunter", "durable-exclude-model",
                        f"{newbl} clamped {len(clamp_events)}x/{THRASH_WINDOW_MIN}min -> canary-only", durable=True)
                _escalate(f"Local model(s) permanently excluded from hot lane: {', '.join(newbl)}",
                          f"They loaded and got RAM-clamped {len(clamp_events)}x in {THRASH_WINDOW_MIN}min "
                          f"(reload/clamp thrash). Now canary-only so they never thrash the fleet again.",
                          "Ends the RAM-clamp thrash loop at the source.")

    # (b) restart storm -> lanes over-subscribed for this box; lower MAX_PARALLEL durably
    restart_n = counts.get("runner-cycled", 0) + counts.get("runner-wedged", 0)
    if restart_n >= RESTART_STORM_N:
        try:
            cur = int(os.environ.get("MAX_PARALLEL", "10"))
            new = max(4, cur - 2)
            if new < cur and _set_fleet_config("MAX_PARALLEL", new):
                _set_fleet_config("MAX_PARALLEL_CEILING", new)
                journal("thrash_hunter", "durable-lower-lanes-restart-storm",
                        f"{restart_n} restarts/{THRASH_WINDOW_MIN}min -> MAX_PARALLEL {cur}->{new}", durable=True)
                _escalate(f"Lanes lowered to {new} after restart storm",
                          f"{restart_n} runner restarts in {THRASH_WINDOW_MIN}min — over-subscribed. Reduced load.",
                          "Stops the restart loop.")
        except Exception:
            pass

    # (c) dedupe recurrence -> already guarded at db.insert; just surface it if still happening a lot
    if counts.get("dedupe", 0) >= 5 and not st.get("dedupe_escalated"):
        journal("thrash_hunter", "dedupe-still-recurring",
                f"{counts['dedupe']} dedupe events/{THRASH_WINDOW_MIN}min despite db guard")
        _escalate("Duplicate task enqueue still recurring",
                  f"{counts['dedupe']} dedupe events in {THRASH_WINDOW_MIN}min. db.insert idempotency guard "
                  "should prevent these — a generator may bypass db.insert. Check medic.jsonl for slugs.",
                  "Non-fatal; sentinel keeps cleaning up.")
        st["dedupe_escalated"] = True
    elif counts.get("dedupe", 0) < 2:
        st["dedupe_escalated"] = False


# ── BOT 3: process_hygiene ────────────────────────────────────────────────────

def process_hygiene():
    # reap multi-hour agent zombies
    for secs, pid, cmd in _agent_procs():
        if secs >= AGENT_MAX_MIN * 60:
            sh("kill", "-9", pid)
            journal("process_hygiene", "reaped-zombie-agent", f"pid={pid} age={secs // 60}min {cmd[:50]}")
    # orphaned build/test processes (parentless, holding CPU — see _orphaned_build_procs)
    try:
        reap_orphaned_builds()
    except Exception:
        pass
    # orphaned home-directory scans (parentless, a full core each — see
    # _orphaned_scan_procs; two of them held this Mac at load 67 on 2026-09-03)
    try:
        reap_orphaned_scans()
    except Exception:
        pass
    # orphaned llama-servers (parentless, holding VRAM)
    try:
        for line in sh("pgrep", "-fl", "llama-server", timeout=15).stdout.splitlines():
            pid = line.split()[0]
            ppid = sh("ps", "-o", "ppid=", "-p", pid, timeout=10).stdout.strip()
            if ppid == "1":
                sh("kill", "-9", pid)
                journal("process_hygiene", "killed-orphan-llama-server", pid)
    except Exception:
        pass
    # rotate oversized runtime logs
    try:
        logs_dir = os.path.join(RUNTIME, "logs")
        cap = LOG_CAP_MB * 1024 * 1024
        for fn in os.listdir(logs_dir) if os.path.isdir(logs_dir) else []:
            fp = os.path.join(logs_dir, fn)
            try:
                if os.path.isfile(fp) and os.path.getsize(fp) > cap:
                    with open(fp, "rb") as f:
                        f.seek(-cap // 2, os.SEEK_END)
                        tail = f.read()
                    with open(fp, "wb") as f:
                        f.write(b"[medic: log rotated]\n" + tail)
                    journal("process_hygiene", "rotated-log", fn)
            except OSError:
                continue
    except Exception:
        pass


# ── BOT 4: loop_breaker (pause/restart oscillation) ───────────────────────────

def loop_breaker(st):
    ev = _recent_events(THRASH_WINDOW_MIN)
    import collections
    counts = collections.Counter(a for _b, a, _d in ev)
    flaps = counts.get("runner-wedged", 0) + counts.get("runner-cycled", 0)
    # if the runner is being cycled repeatedly AND memory is fine, the cycling itself is the
    # problem (my restarts resetting work) — back off: request a cool-down flag other guards honor.
    if flaps >= RESTART_STORM_N and (memory_free_pct() or 100) >= PRESSURE_WARN:
        cool_until = time.time() + int(os.environ.get("MEDIC_COOLDOWN_S", "1800"))
        st["restart_cooldown_until"] = cool_until
        journal("loop_breaker", "restart-cooldown",
                f"{flaps} cycles/{THRASH_WINDOW_MIN}min with healthy RAM -> 30min cool-down (stop churn)")


def main():
    st = load_state()
    cycle_start = time.monotonic()
    timings = {}
    for bot, fn in (("memory_guard", lambda: memory_guard(st)),
                    ("thrash_hunter", lambda: thrash_hunter(st)),
                    ("process_hygiene", process_hygiene),
                    ("loop_breaker", lambda: loop_breaker(st))):
        t0 = time.monotonic()
        try:
            fn()
        except Exception as e:
            journal(bot, "error", str(e)[:120])
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        timings[bot] = elapsed_ms
        if elapsed_ms > 5000:
            journal(bot, "slow-bot", f"{elapsed_ms}ms (>5s threshold)")
    cycle_ms = int((time.monotonic() - cycle_start) * 1000)
    st["last_run"] = _now().isoformat() + "Z"
    st["last_cycle_ms"] = cycle_ms
    st["last_timings"] = timings
    save_state(st)
    if cycle_ms > 15000:
        journal("main", "slow-cycle", f"total {cycle_ms}ms: {timings}")


if __name__ == "__main__":
    main()
