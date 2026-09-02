#!/usr/bin/env python3
"""Fleet-wide limit on how many production builds run at once.

WHY THIS EXISTS
---------------
build_gate.run_build() shells out to the project's real production build -- `nuxt build`
for most of this fleet -- and nothing anywhere limited how many ran at the same time.
merge_train runs MERGE_TRAIN_PROJECT_WORKERS (4) project workers in one process, and
build_daemon and release_train build from their own processes, so the ceiling was however
many happened to coincide.

A Nuxt build here is not a small process. Measured on this host 2026-09-02:

    RAM                                 48 GB
    concurrent nuxt builds               4
    their combined RSS                16.1 GB   (4.5 + 5.2 + 4.8 + 1.6)
    one build's own NODE_OPTIONS      --max-old-space-size=16384
    swap total / used            15,360 MB / 14,432 MB   (94%)
    free RAM                           ~64 MB at the low point

Sampled over 50s with only two builds running, the machine still sat at 9.26 GB of build
RSS, 6.25 GB free and swap pinned at 14,432 MB -- saturated, with nowhere left to page.

That is the real cost driver behind everything else that looked slow: `tomorrow`'s gate
suite takes 489s under this pressure against 131s on an idle machine, the load average
sits near twice the core count while the orchestrator's own Python processes account for
only 36.6% CPU between them, and the one `v8::OOMDetails` crash in the merge-train log is
a build that actually ran out of memory and was recorded as if the candidate's tests had
failed.

Four builds each allowed a 16 GB heap on a 48 GB machine is not a tuning question, it is
an unbounded resource. This bounds it.

DESIGN
------
* Cross-PROCESS, because the builders are separate processes: N lock files, each taken
  with a non-blocking flock. This mirrors repo_lock, which solves the same shape of
  problem for git refs.
* Memory-aware: a slot is not enough on its own. If free memory is already below the
  floor, holding a slot and starting a 5 GB build just moves the thrash around, so the
  acquire waits for headroom too.
* FAILS OPEN, deliberately, and this is the opposite of repo_lock's choice. repo_lock
  fails closed because a missed lock corrupts refs. Here the worst case of proceeding
  without a slot is a slow build; the worst case of refusing is a BUILDFAIL on a
  candidate whose only sin was arriving when the machine was busy -- turning a resource
  problem into a false verdict against someone's code, which is the exact class of bug
  this session has spent the day removing. So: wait up to ORCH_BUILD_SLOT_WAIT_S, then
  proceed anyway and say so loudly.
"""
import contextlib
import errno
import fcntl
import os
import time

#: Default slot directory, resolved at import for callers that read the constant.
#: Prefer slot_dir(): it is read at CALL time and honours CLAUDE_ORCH_HOME.
SLOT_DIR = os.environ.get(
    "ORCH_BUILD_SLOT_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), ".runtime", "build-slots"),
)


def slot_dir():
    """Where the slot files live, resolved at call time.

    TESTS MUST NOT CONTEND WITH THE LIVE FLEET. The path used to be a module constant
    fixed at import, so any test that reached a real hold() took a lock in the
    orchestrator's OWN .runtime/build-slots and waited on the machine's real builds --
    up to ORCH_BUILD_SLOT_WAIT_S (900s) of it. On 2026-09-02, once the limiter was wired
    into the suite path as well as the gates, that surfaced as a clean_clone_gate test
    timing out while two production builds held both slots.

    This is the same defect the CLAUDE_ORCH_HOME fixture in tests/conftest.py exists to
    prevent for every other runtime writer -- 94 modules honour it, this one did not.
    Explicit ORCH_BUILD_SLOT_DIR still wins, so an operator can point the fleet at a
    specific directory.
    """
    override = os.environ.get("ORCH_BUILD_SLOT_DIR")
    if override:
        return override
    home = os.environ.get("CLAUDE_ORCH_HOME")
    if home:
        return os.path.join(home, "build-slots")
    return SLOT_DIR

#: Two, not one: a single slot serialises the whole fleet's builds behind the slowest
#: repo, and two 5 GB builds still fit on a 48 GB machine with the memory floor below.
DEFAULT_MAX_CONCURRENT = 2
#: Long enough for one Nuxt build to finish and free its slot, well inside the
#: merge-train watchdog's 2700s budget.
DEFAULT_WAIT_BUDGET_S = 900.0
#: Used only when resource_governor cannot be read; deliberately conservative.
FALLBACK_MIN_FREE_GB = 4.0
#: How long to sleep between attempts to take a slot.
POLL_INTERVAL_S = 5.0
#: A wait shorter than one poll is not worth a log line.
LOG_WAIT_THRESHOLD_S = 5.0


def max_concurrent():
    """How many production builds may run at once. Read at call time."""
    try:
        return max(1, int(os.environ.get("ORCH_MAX_CONCURRENT_BUILDS",
                                        str(DEFAULT_MAX_CONCURRENT))))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CONCURRENT


def wait_budget_s():
    """How long to wait for a slot before proceeding anyway."""
    try:
        return max(0.0, float(os.environ.get("ORCH_BUILD_SLOT_WAIT_S",
                                            str(DEFAULT_WAIT_BUDGET_S))))
    except (TypeError, ValueError):
        return DEFAULT_WAIT_BUDGET_S


def min_free_gb():
    """Free memory below which a build should not be STARTED.

    Defaults to resource_governor's own RAM floor so the two agree about "tight", and
    falls back to a conservative 4 GB when that module cannot be read.
    """
    raw = os.environ.get("ORCH_BUILD_MIN_FREE_GB")
    if raw:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            return FALLBACK_MIN_FREE_GB    # a bad override is not an absent one
    try:
        import resource_governor
        return float(resource_governor._ram_floor_gb())
    except Exception:
        return FALLBACK_MIN_FREE_GB


def free_gb():
    """Available memory in GB, or None when it cannot be measured."""
    try:
        import resource_governor
        _pct, avail = resource_governor._vm_stat()
        return float(avail)
    except Exception:
        return None


def _slot_paths():
    base = slot_dir()
    return [os.path.join(base, "build-%02d.slot" % i) for i in range(max_concurrent())]


def _try_take(path):
    """Take one slot, or return None. Never raises."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        handle = open(path, "a+")
    except OSError:
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
            return None
        return None
    try:
        handle.seek(0)
        handle.truncate()
        handle.write("pid=%d at=%d\n" % (os.getpid(), int(time.time())))
        handle.flush()
    except OSError:
        return handle      # the slot is held; only its bookkeeping stamp failed
    return handle


#: Command fragments that mean "this is a production build", not a test run. Kept
#: deliberately narrow: every entry here costs throughput if it matches an ordinary
#: suite, and the failure mode of missing one is only the status quo.
_BUILD_COMMANDS = (
    "npm run build", "pnpm run build", "pnpm build", "yarn build", "yarn run build",
    "npm run build:", "nuxt build", "nuxi build", "next build", "vite build",
)


def command_builds(command):
    """True when this suite/QA command actually runs a production build.

    A project can have its TEST command set to a build. Measured 2026-09-02, the
    fleet's own projects table:

        kalepasch-com   test_cmd = "npm run build"

    so its merge-train suite and its release QA both compile the app, in a
    release-qa-overlay, outside build_gate -- which is why three concurrent nuxt
    builds were observed against a limit of two, minutes after that project was
    unpaused. The limiter bounded the build GATES; nothing bounded a suite that is a
    build wearing a suite's name.
    """
    text = (command or "").lower()
    return any(marker in text for marker in _BUILD_COMMANDS)


@contextlib.contextmanager
def hold_if_build(command, label="suite", log=print):
    """Hold a slot only when `command` is a production build; otherwise a no-op.

    Suites are this fleet's throughput and must not be serialised. This exists so a
    suite that IS a build stops being invisible to the limiter, and nothing else
    changes.
    """
    if not command_builds(command):
        yield None            # None, not False: "no slot was needed", not "denied one"
        return
    with hold(label, log=log) as got:
        yield got


@contextlib.contextmanager
def hold(label="build", log=print):
    """Hold a build slot for the duration of the block.

    Yields True when a slot (and memory headroom) was obtained, False when the wait
    budget ran out and the caller is proceeding anyway. Never raises, never blocks
    forever, and always releases.
    """
    deadline = time.monotonic() + wait_budget_s()
    handle = None
    waited = 0.0
    floor = min_free_gb()
    while True:
        for path in _slot_paths():
            handle = _try_take(path)
            if handle:
                break
        if handle:
            avail = free_gb()
            if avail is None or avail >= floor:
                break
            # Slot in hand but the machine has no headroom: give the slot back rather
            # than sitting on it, so a build that finishes can free memory for everyone.
            _release(handle)
            handle = None
        if time.monotonic() >= deadline:
            log("[build-slots] %s: no slot after %.0fs (limit %d, free %s GB) — "
                "proceeding anyway; a slow build beats a false BUILDFAIL"
                % (label, waited, max_concurrent(),
                   "unknown" if free_gb() is None else "%.1f" % free_gb()))
            break
        time.sleep(POLL_INTERVAL_S)
        waited = wait_budget_s() - max(0.0, deadline - time.monotonic())
    if handle and waited >= LOG_WAIT_THRESHOLD_S:
        log("[build-slots] %s: waited %.0fs for a slot (limit %d)"
            % (label, waited, max_concurrent()))
    try:
        yield handle is not None
    finally:
        _release(handle)


def _release(handle):
    if not handle:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        handle.close()     # closing releases the flock regardless
        return None
    try:
        handle.close()
    except OSError:
        return None        # already closed; the slot is free either way


def in_use():
    """How many slots are currently held. Diagnostics only; racy by nature."""
    held = 0
    for path in _slot_paths():
        handle = _try_take(path)
        if handle:
            _release(handle)
        else:
            held += 1
    return held
