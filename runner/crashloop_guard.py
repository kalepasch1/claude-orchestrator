"""
crashloop_guard.py — stop scheduled jobs from failing SILENTLY in a loop.

THE MEASURED FAILURE
    The merge train is spawned by the scheduler every 60s. Its entry point calls a startup
    gate that RE-RAISES RuntimeError, and train_run()'s first act is db.select("projects"),
    which raises TransientDBError on any DNS blip. Neither is caught, so both end as an
    unhandled traceback: nonzero exit, a fresh stack dump appended to merge-train.err, and
    the scheduler starts another one a minute later. Measured on this host: 444 KB of
    merge-train.err, 87 tracebacks of one job (78% of that job's total), of which 265 were
    the SAME undefined name repeated, plus 9 transient DNS failures and 31 watchdog kills.

    Nothing was alerted. The log grew, merges stopped, and the only signal was that the
    queue stopped draining. That is what "failing silently in a crash loop" means here, and
    the silence is the actual defect — the underlying causes were each individually easy to
    fix once someone read the stack.

WHAT THIS FIXES
    Three different things happen when a scheduled pass ends badly, and they need three
    different behaviours. Collapsing them all into "unhandled traceback" is why the loop
    was invisible:

      REFUSED   a startup gate deliberately said no (e.g. static_sanity found an undefined
                name in a critical loop). This is the gate WORKING. It should print one
                actionable line and exit 3 — not dump a stack that looks like a bug.
      SKIPPED   a transient dependency failure (DNS, connection refused, timeout). The next
                pass is a minute away and will probably succeed. Exit 0, one line, no stack.
      CRASHED   anything else. Genuinely unexpected: keep the full traceback, exit 1.

    On top of that, every outcome is DEDUPLICATED against the previous pass, and a cause
    that repeats past a threshold is escalated ONCE to coordination_tasks so a human or a
    triage bot sees it. A repeating failure that has already been reported prints a single
    "repeat xN" line instead of another stack — the log stays readable and the signal stays.

USE
    from crashloop_guard import guarded_main
    if __name__ == "__main__":
        sys.exit(guarded_main("merge-train", _run_one_pass))

DESIGN RULES
    - the guard itself must never be the reason a job dies: every helper is fail-soft and
      a failure inside the guard falls back to running the job unguarded.
    - state lives in one small JSON file under CLAUDE_ORCH_HOME; losing it only costs a
      duplicate escalation.
    - no new dependencies; db is imported lazily so a job can be guarded on a host with no
      database reachable (which is precisely the SKIPPED case).
"""
import json
import os
import sys
import time
import traceback

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

__all__ = ["guarded_main", "classify", "record_outcome", "REFUSED", "SKIPPED",
           "CRASHED", "OK"]

OK, REFUSED, SKIPPED, CRASHED = "ok", "refused", "skipped", "crashed"

EXIT_CODE = {OK: 0, SKIPPED: 0, CRASHED: 1, REFUSED: 3}

STATE = os.path.join(
    os.environ.get("CLAUDE_ORCH_HOME",
                   os.path.join(os.path.dirname(_DIR), ".runtime")),
    "crashloop-guard.json")

# How many identical consecutive failures before the loop is escalated. 1 would page on a
# single DNS blip; the point is to catch a LOOP, so require a repeat.
ESCALATE_AFTER = int(os.environ.get("ORCH_CRASHLOOP_ESCALATE_AFTER", "3"))

# Exception names that mean "the dependency was briefly unavailable", not "the code is
# wrong". Matched by class name so this module never has to import db or urllib.
TRANSIENT_NAMES = {n.strip() for n in os.environ.get(
    "ORCH_CRASHLOOP_TRANSIENT",
    "TransientDBError,URLError,HTTPError,ConnectionError,ConnectionRefusedError,"
    "ConnectionResetError,TimeoutError,socket.timeout,IncompleteRead,RemoteDisconnected,"
    "SSLError,BadStatusLine").split(",") if n.strip()}


# ── classification ────────────────────────────────────────────────────────────

def _names(exc):
    """Every exception class name in the raise chain (cause and context)."""
    seen, out, cur = set(), [], exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        out.append(type(cur).__name__)
        cur = cur.__cause__ or cur.__context__
    return out


def classify(exc, refused_types=(RuntimeError,)):
    """REFUSED / SKIPPED / CRASHED for a raised exception.

    Transient wins over refused: a RuntimeError raised *because* the network was down is a
    skipped pass, not a policy refusal, and treating it as a refusal would exit 3 forever.
    """
    try:
        names = _names(exc)
        if TRANSIENT_NAMES.intersection(names):
            return SKIPPED
        if isinstance(exc, tuple(refused_types or ())):
            return REFUSED
        return CRASHED
    except Exception:
        return CRASHED


def signature(job, outcome, exc):
    """Stable identity of a failure, so 'the same thing again' is detectable.

    Deliberately excludes the message body: a message carrying a timestamp, a task id or a
    host name would defeat deduplication entirely, which is how 265 copies of one undefined
    name reached the log.
    """
    try:
        frame = ""
        tb = getattr(exc, "__traceback__", None)
        while tb is not None:      # innermost frame — where it actually broke
            frame = f"{os.path.basename(tb.tb_frame.f_code.co_filename)}:{tb.tb_lineno}"
            tb = tb.tb_next
        return f"{job}|{outcome}|{type(exc).__name__}|{frame}"
    except Exception:
        return f"{job}|{outcome}|{type(exc).__name__}"


# ── state ─────────────────────────────────────────────────────────────────────

def _load():
    try:
        with open(STATE) as fh:
            return json.load(fh) or {}
    except Exception:
        return {}


def _save(state):
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(state, fh)
        os.replace(tmp, STATE)
    except Exception:
        pass


def record_outcome(job, outcome, sig=None):
    """Update the per-job streak. Returns {"streak", "repeat", "escalate"}.

    escalate is True EXACTLY ONCE per distinct cause, at the threshold — a loop that is
    already reported must not re-file a card on every tick, or the escalation channel
    becomes the new place where the signal is lost.
    """
    info = {"streak": 1, "repeat": False, "escalate": False}
    try:
        state = _load()
        prev = state.get(job) or {}
        same = bool(sig) and prev.get("signature") == sig
        streak = (prev.get("streak", 0) + 1) if same else 1
        already = bool(prev.get("escalated")) and same
        escalate = (outcome in (REFUSED, CRASHED) and streak >= ESCALATE_AFTER
                    and not already)
        state[job] = {"signature": sig, "streak": streak, "outcome": outcome,
                      "escalated": already or escalate,
                      "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if outcome == OK:
            state[job] = {"signature": None, "streak": 0, "outcome": OK,
                          "escalated": False, "at": state[job]["at"]}
        _save(state)
        info = {"streak": streak, "repeat": same, "escalate": escalate}
    except Exception:
        pass
    return info


def _escalate(job, outcome, sig, detail):
    """File one coordination task so the loop stops being silent. Fail-soft."""
    try:
        import db
        db.insert("coordination_tasks", {
            "task_type": "crashloop_alert",
            "payload": json.dumps({
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "job": job, "outcome": outcome, "signature": sig,
                "detail": (detail or "")[-4000:],
            })[:8000]}, upsert=False)
        return True
    except Exception:
        return False


# ── entry point ───────────────────────────────────────────────────────────────

def guarded_main(job, fn, refused_types=(RuntimeError,), quiet_repeats=True):
    """Run one scheduled pass. Returns the process exit code; never raises.

    A guarded job that keeps failing produces ONE readable line per tick and one alert per
    distinct cause, instead of an unbounded pile of identical stack traces nobody reads.
    """
    try:
        fn()
    except SystemExit as e:                      # the job chose its own exit code
        return int(getattr(e, "code", 0) or 0)
    except BaseException as exc:                 # noqa: BLE001 - deliberate top-level net
        try:
            return _report(job, exc, refused_types, quiet_repeats)
        except Exception as guard_bug:
            # A bug in the reporting path must not become the new unhandled traceback. The
            # whole premise of this module is that the guard can never be the reason a job
            # dies, and that has to hold for the guard's own code too.
            print(f"{job}: crashloop_guard failed while reporting "
                  f"({type(guard_bug).__name__}: {guard_bug}); original failure: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            return 1

    record_outcome(job, OK, None)
    return 0


def _report(job, exc, refused_types, quiet_repeats):
    """Classify, log and (once per distinct cause) escalate one failed pass.

    Returns the exit code. May raise — guarded_main() owns the last resort.
    """
    outcome = classify(exc, refused_types=refused_types)
    sig = signature(job, outcome, exc)
    streak = record_outcome(job, outcome, sig)
    msg = f"{type(exc).__name__}: {exc}".strip()

    if outcome == SKIPPED:
        print(f"{job}: SKIPPED this pass — dependency unavailable ({msg[:200]}). "
              f"Not an error; the next scheduled pass will retry.",
              file=sys.stderr, flush=True)
    elif outcome == REFUSED:
        print(f"{job}: REFUSED to run — a startup gate rejected this build. {msg[:400]}",
              file=sys.stderr, flush=True)
        print(f"{job}: this is the gate working, not a crash. Fix the reported cause; "
              f"the job will start on its own once it is green.",
              file=sys.stderr, flush=True)
    else:
        # Genuinely unexpected: the traceback is the payload. Print it once per distinct
        # cause; after that the streak line carries the same information in one line.
        if streak["repeat"] and quiet_repeats:
            print(f"{job}: CRASHED again (same cause, x{streak['streak']}): {msg[:200]}",
                  file=sys.stderr, flush=True)
        else:
            print(f"{job}: CRASHED — {msg[:400]}", file=sys.stderr, flush=True)
            traceback.print_exc()

    if streak["repeat"]:
        print(f"{job}: crash-loop streak={streak['streak']} signature={sig}",
              file=sys.stderr, flush=True)
    if streak["escalate"]:
        filed = _escalate(job, outcome, sig, msg)
        print(f"{job}: escalated crash loop to coordination_tasks "
              f"({'filed' if filed else 'could not file'})",
              file=sys.stderr, flush=True)
    return EXIT_CODE.get(outcome, 1)
