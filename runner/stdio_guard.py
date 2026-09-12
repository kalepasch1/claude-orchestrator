#!/usr/bin/env python3
"""A `print` must never be able to fail a gate.

WHAT HAPPENED.

Between 2026-09-02 and 2026-09-03 the fleet's single largest release-failure
note was:

    [gate:qa] staging QA failed (tests required) — self-heal queued:
    QA overlay failed: [Errno 32] Broken pipe

Eight projects, ~4 an hour. It is not a QA result at all. It is a `print`.

`db_recovery_sprint._run()` launches eight jobs with
`subprocess.run(cmd, capture_output=True, timeout=...)` — release_train at 600s
and autopilot at 240s among them, 2280s of budget in a process the scheduler
reaps long before that. When the sprint is reaped, its in-flight child is
reparented to PID 1 and keeps the capture pipes whose READ ends died with the
parent. Observed live on 2026-09-03:

    PID 53526  PPID 1  autopilot.py       fd 1 -> PIPE (no reader)
    PID  5373  PPID 1  merge_train.py     fd 1 -> PIPE (no reader)
    PID 44407  PPID 18848 (live runner)   fd 1 -> .runtime/logs/autopilot.log

The orphan keeps running a full release train. Its database writes succeed —
that is a socket, not the pipe — so it goes on recording release rows. But every
`print` it reaches raises BrokenPipeError, and release_train's QA block catches
`Exception`, so a dead log pipe was being written down as a failed suite. Rows
that flip a project RED and trip release back-pressure fleet-wide.

WHAT THIS DOES.

Writes to stdout/stderr that fail with EPIPE (or EBADF) stop raising. The stream
is swapped, once, for the process's log file if one can be opened and os.devnull
otherwise, and a single line is recorded so the swap itself is not silent.

WHAT THIS DOES NOT DO.

It does not touch any other error. A full disk (ENOSPC) on the log still raises,
because that is a real fault and hiding it would be the same mistake in the
other direction. And it is not a substitute for not orphaning the process --
see `orphaned()`, which is how a reaped-parent leftover is meant to stand down
rather than run a second release train.
"""
from __future__ import annotations

import errno
import io
import os
import sys

#: The write errors that mean "nobody is reading this", never "this write was wrong".
DEAD_READER_ERRNOS = frozenset({errno.EPIPE, errno.EBADF})

_installed = False


def _dead_reader(exc):
    if isinstance(exc, BrokenPipeError):
        return True
    return isinstance(exc, OSError) and exc.errno in DEAD_READER_ERRNOS


def _fallback(name):
    """Where output goes once the original stream is known dead."""
    for candidate in (os.environ.get("ORCH_STDIO_FALLBACK"),
                      _log_path(name)):
        if not candidate:
            continue
        try:
            return open(candidate, "a", buffering=1, encoding="utf-8",
                        errors="replace")
        except OSError:
            continue
    return open(os.devnull, "w", encoding="utf-8")


def _log_path(name):
    base = os.environ.get("ORCH_LOG_DIR")
    if not base:
        home = os.environ.get("CLAUDE_ORCH_HOME")
        base = os.path.join(home, "logs") if home else None
    if not base:
        return None
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        return None
    process = os.path.basename(sys.argv[0] or "orch").replace(".py", "") or "orch"
    return os.path.join(base, f"{process}-orphaned-{name}.log")


class EpipeSafeStream(io.TextIOBase):
    """Delegates to `stream`; on a dead reader, swaps to a file and keeps going."""

    #: Bytes of not-yet-flushed output kept so a swap can re-emit it. Python's
    #: TextIOWrapper buffers, so the write that FILLS the buffer succeeds and the
    #: flush that drains it is what raises -- by which point the line that caused
    #: the swap is stranded inside the dead stream, unreachable. Holding our own
    #: copy until a flush actually lands is what stops that line being lost.
    #: Capped, because an unflushed stream must not be able to grow without bound.
    PENDING_CAP_BYTES = 256 * 1024

    def __init__(self, stream, name):
        self._stream = stream
        self._name = name
        self._swapped = False
        self._pending = []
        self._pending_bytes = 0

    # -- the part that matters -------------------------------------------------
    def write(self, data):
        try:
            written = self._stream.write(data)
        except Exception as exc:
            if not _dead_reader(exc):
                raise
            self._swap(exc)
            return self._write_through(data)
        self._remember(data)
        return written

    def flush(self):
        try:
            self._stream.flush()
        except Exception as exc:
            if not _dead_reader(exc):
                raise
            self._swap(exc)          # re-emits whatever the dead buffer swallowed
            return
        self._forget()

    def _remember(self, data):
        if self._swapped:
            return
        self._pending.append(data)
        self._pending_bytes += len(data)
        while self._pending_bytes > self.PENDING_CAP_BYTES and len(self._pending) > 1:
            self._pending_bytes -= len(self._pending.pop(0))

    def _forget(self):
        self._pending = []
        self._pending_bytes = 0

    def _write_through(self, data):
        try:
            self._stream.write(data)
            self._stream.flush()
        except Exception:
            pass
        return len(data)

    def _swap(self, exc):
        if self._swapped:
            return
        self._swapped = True
        stranded = "".join(self._pending)
        self._forget()
        replacement = _fallback(self._name)
        self._stream = replacement
        try:
            replacement.write(
                f"[stdio-guard] {self._name} had no reader ({exc}); "
                f"this process is most likely an orphan of a reaped parent. "
                f"Output continues here.\n")
            if stranded:
                replacement.write(stranded)
            replacement.flush()
        except Exception:
            pass

    # -- passthrough -----------------------------------------------------------
    @property
    def swapped(self):
        return self._swapped

    def writable(self):
        return True

    def isatty(self):
        try:
            return self._stream.isatty()
        except Exception:
            return False

    def fileno(self):
        return self._stream.fileno()

    def __getattr__(self, item):
        return getattr(self._stream, item)


def install():
    """Make this process's stdout/stderr survive losing their reader. Idempotent."""
    global _installed
    if _installed:
        return False
    sys.stdout = EpipeSafeStream(sys.stdout, "stdout")
    sys.stderr = EpipeSafeStream(sys.stderr, "stderr")
    _installed = True
    return True


def orphaned():
    """True when this process is a reaped parent's leftover, still holding dead pipes.

    Both halves are required. A PPID of 1 alone is ordinary for a deliberately
    detached daemon, and a piped stdout alone is ordinary for a job whose parent
    is reading it. It is the COMBINATION that means the parent that was capturing
    this output is gone -- which is exactly the state in which a release train
    should stand down rather than compete with the live one for leases, build
    slots and release rows.
    """
    try:
        if os.getppid() != 1:
            return False
    except OSError:
        return False
    return _reader_is_gone(1) or _reader_is_gone(2)


def _reader_is_gone(fd):
    """True when `fd` is a pipe whose read end has closed.

    Asked with poll(), not with a probe write. A zero-byte `os.write` to a pipe
    is defined to return 0 without touching the pipe -- it does NOT raise EPIPE
    even when the reader is gone -- and a one-byte probe would corrupt the log
    of a healthy process. poll() reports POLLERR/POLLHUP on the write end of a
    pipe whose read end has closed, and asks nothing of a live one.
    """
    import select
    import stat
    try:
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            return False
    except OSError:
        return False
    try:
        poller = select.poll()
        poller.register(fd, select.POLLOUT)
        for _, event in poller.poll(0):
            if event & (select.POLLERR | select.POLLHUP | select.POLLNVAL):
                return True
    except Exception:
        return False
    return False
