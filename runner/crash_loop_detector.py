#!/usr/bin/env python3
"""
crash_loop_detector.py - the meta-bot: notice when a bot itself is dead.

The deepest failure of 2026-08-02 was not a bad deploy, it was SILENCE. preflight_gate.py raised

    AttributeError: module 'pipeline_contract' has no attribute 'task_fields'

on EVERY invocation for 19 days — 4,961 identical tracebacks in .runtime/logs/preflight.err — and
nothing noticed, because a scheduled job that dies writes to .err and exits 1, and no one reads
.err. Same story for ~31k NameErrors and ~10k `_elapsed_ms` failures. A fleet of bots with no bot
watching the bots has no floor.

This scans .runtime/logs/*.err, normalises each traceback to a stable SIGNATURE (exception type +
message shape + last frame, with paths/numbers/hex stripped), and fires when a signature is:

  * REPEATING      - more than ORCH_CRASH_LOOP_MIN_HITS occurrences (default 50) in the window, or
  * DOMINANT       - >= ORCH_CRASH_LOOP_DOMINANCE (default 90%) of that job's tracebacks, or
  * MODULE DEAD    - the job has >= N tracebacks and NO evidence of a successful run at all
                     (its .log is empty or stale relative to .err) -> 100% failure rate.

Firing = a real alert (notify + an approvals card) AND an auto-filed remediation task carrying the
traceback. State in .runtime/crash-loop-state.json deduplicates by signature, so a still-broken
job does not re-alert every cycle — it re-alerts only after a cooldown or a 10x escalation.

Structured JSONL goes to .runtime/logs/crash-loop-detector.log.
"""
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import guard_tasks

NAME = "crash-loop-detector"
ENABLED = os.environ.get("ORCH_CRASH_LOOP_ENABLED", "true").lower() in ("1", "true", "yes", "on")
FILE_TASKS = os.environ.get("ORCH_CRASH_LOOP_FILE_TASKS", "true").lower() in ("1", "true", "yes", "on")
MIN_HITS = int(os.environ.get("ORCH_CRASH_LOOP_MIN_HITS", "50"))
DOMINANCE = float(os.environ.get("ORCH_CRASH_LOOP_DOMINANCE", "0.90"))
DOMINANCE_MIN = int(os.environ.get("ORCH_CRASH_LOOP_DOMINANCE_MIN", "10"))
DEAD_MIN_ATTEMPTS = int(os.environ.get("ORCH_CRASH_LOOP_DEAD_MIN_ATTEMPTS", "20"))
WINDOW_HOURS = float(os.environ.get("ORCH_CRASH_LOOP_WINDOW_HOURS", "72"))
TAIL_BYTES = int(os.environ.get("ORCH_CRASH_LOOP_TAIL_BYTES", str(4 * 1024 * 1024)))
COOLDOWN_S = float(os.environ.get("ORCH_CRASH_LOOP_COOLDOWN_S", "86400"))
ESCALATION = float(os.environ.get("ORCH_CRASH_LOOP_ESCALATION", "10"))
STALE_LOG_S = float(os.environ.get("ORCH_CRASH_LOOP_STALE_LOG_S", "3600"))

# Infrastructure weather, not a code defect: DNS blips, 5xx/429 from Supabase, reset sockets.
# These crowd out real crash loops (they were 60% of the first live scan), so they only fire when
# they are ALSO the sole failure mode of a module that never succeeds. A 400/404 is NOT here on
# purpose — a malformed PostgREST query or a missing endpoint is a code bug, not weather.
_TRANSIENT = re.compile(
    r"HTTP Error 5\d\d|HTTP Error 429|URLError|nodename nor servname|Connection reset|"
    r"ConnectionResetError|ConnectionRefusedError|TimeoutError|timed out|"
    r"TransientDBError|RemoteDisconnected|IncompleteRead", re.I)
MAX_FIRES = int(os.environ.get("ORCH_CRASH_LOOP_MAX_FIRES", "5"))
# Alerting is throttled to MAX_FIRES so the operator is not spammed; task FILING has its own,
# larger budget so a backlog of real crash loops still becomes real work within a few cycles.
MAX_TASKS_PER_RUN = int(os.environ.get("ORCH_CRASH_LOOP_MAX_TASKS_PER_RUN", "12"))

_TB_START = re.compile(r"^Traceback \(most recent call last\):\s*$")
_FRAME = re.compile(r'^\s+File "([^"]+)", line (\d+), in (\S+)')
_EXC = re.compile(r"^([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Warning|Failure))\b:?(.*)$")
# Noise that makes two identical bugs look like two different bugs.
_NOISE = (
    (re.compile(r"0x[0-9a-fA-F]+"), "0xHEX"),
    (re.compile(r"\b[0-9a-f]{7,40}\b"), "SHA"),
    (re.compile(r"\d+"), "N"),
    (re.compile(r"'/[^']*'"), "'PATH'"),
    (re.compile(r"\s+"), " "),
)


def _home():
    return os.environ.get("CLAUDE_ORCH_HOME",
                          os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".runtime"))


def _log_dir():
    return os.path.join(_home(), "logs")


def _state_path():
    return os.path.join(_home(), "crash-loop-state.json")


def _log_event(event):
    """Append one structured JSONL record to .runtime/logs/<name>.log (fail-soft)."""
    row = dict(event)
    row.setdefault("at", time.time())
    row.setdefault("bot", NAME)
    try:
        os.makedirs(_log_dir(), exist_ok=True)
        with open(os.path.join(_log_dir(), NAME + ".log"), "a") as f:
            f.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    except OSError:
        pass
    return row


def _load_state():
    try:
        with open(_state_path()) as f:
            return json.load(f) or {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    try:
        os.makedirs(os.path.dirname(_state_path()), exist_ok=True)
        tmp = _state_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f, separators=(",", ":"), default=str)
        os.replace(tmp, _state_path())
        return True
    except OSError:
        return False


def normalize(text):
    """Collapse a traceback's variable parts so identical bugs share one signature."""
    value = str(text or "").strip()
    for pattern, repl in _NOISE:
        value = pattern.sub(repl, value)
    return value.strip()[:300]


def signature(exception_line, last_frame):
    """A stable id for one crash: normalised exception + the frame that raised it."""
    key = "%s|%s" % (normalize(exception_line), normalize(last_frame))
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]


def parse_tracebacks(text):
    """Extract every Python traceback from a log body.

    Returns [{"signature","exception","last_frame","body"}]. Tolerates interleaved/partial output
    (multiple jobs append to the same .err), which is why it re-syncs on each 'Traceback' header.
    """
    found = []
    lines = str(text or "").splitlines()
    i = 0
    while i < len(lines):
        if not _TB_START.match(lines[i]):
            i += 1
            continue
        block, last_frame = [lines[i]], ""
        i += 1
        while i < len(lines):
            line = lines[i]
            if _TB_START.match(line):
                break
            block.append(line)
            frame = _FRAME.match(line)
            if frame:
                last_frame = "%s:%s in %s" % (os.path.basename(frame.group(1)), frame.group(2), frame.group(3))
                i += 1
                continue
            exc = _EXC.match(line.strip()) if line.strip() and not line.startswith(" ") else None
            if exc:
                i += 1
                found.append({"signature": signature(line.strip(), last_frame),
                              "exception": line.strip()[:400], "last_frame": last_frame,
                              "body": "\n".join(block)[-2500:]})
                break
            i += 1
        else:
            break
    return found


RECENCY_GATE = os.environ.get(
    "ORCH_CRASH_LOOP_RECENCY_GATE", "true").lower() in ("1", "true", "yes", "on")


RECENT_BYTES = int(os.environ.get("ORCH_CRASH_LOOP_RECENT_BYTES", str(256 * 1024)))
# A job crashing on its most recent invocation still has that traceback at EOF. This many
# trailing lines are always scanned, so the success-line cut can never hide a live loop.
CRASHING_TAIL_LINES = int(os.environ.get("ORCH_CRASH_LOOP_CRASHING_TAIL_LINES", "80"))


def live_tail(text, recent_bytes=None):
    """Narrow a 4MB scan window to the job's most recent activity.

    WHY: the freshness gate in scan() is `os.path.getmtime(<job>.err)`, but .err is not a
    traceback-only stream — jobs write ordinary progress lines and `[db] TRUNCATED SCAN`
    warnings to stderr too. Any job that logs at all keeps its .err mtime fresh forever, so
    every historical traceback still sitting in the 4MB tail reads as current.

    That is not hypothetical. `credresolver` was reported at "critical x134 99.3%" for
    `NameError: run_editorial`, a bug fixed days earlier: the last NameError sat 474KB from
    the end of a 591KB file, followed by nothing but successful "[cred-resolver]
    auto-resolved ..." lines. Six other jobs carried the same ghost, and those findings are
    what refill the backlog with tasks to fix bugs that are already fixed. `share`
    compounds it — classify() divides by the traceback count, so it measures share OF
    FAILURES, never a failure rate: 134 dead tracebacks plus 5,000 later successes scores
    99.3%.

    Because these logs are append-only, distance from EOF is a usable proxy for recency,
    and unlike "cut at the last successful line" it cannot swallow a live crash loop —
    a job failing right now has its traceback at EOF, inside any window. `merge-train`,
    whose .err ends mid-crash, survives this gate; the seven `run_editorial` ghosts do not.

    Set ORCH_CRASH_LOOP_RECENT_BYTES=0 to disable narrowing entirely.
    """
    body = str(text or "")
    limit = RECENT_BYTES if recent_bytes is None else recent_bytes
    if limit > 0 and len(body) > limit:
        window = body[-limit:]
        # Never start mid-traceback: a partial block would lose the frames that form its
        # signature, so drop back to the first complete record in the window.
        start = window.find("Traceback (most recent call last):")
        body = window if start <= 0 else window[start:]

    lines = body.splitlines()
    # (b) A job failing RIGHT NOW has a traceback at the end of its log. Whatever the
    # success-line analysis concludes, never discard the last CRASHING_TAIL_LINES — that is
    # what keeps a live loop (merge-train ends mid-crash) from being gated away.
    floor = max(0, len(lines) - CRASHING_TAIL_LINES)

    # (a) Otherwise a signature only counts if it postdates the job's last completed
    # invocation. Success lines are unindented, non-exception, and outside a traceback;
    # frames inside faulthandler-style dumps are indented and must not reset the cut.
    cut, in_traceback = 0, False
    for index, line in enumerate(lines):
        if _TB_START.match(line):
            in_traceback = True
            continue
        if line.startswith((" ", "\t")) or not line.strip():
            continue
        if in_traceback:
            if _EXC.match(line.strip()):
                in_traceback = False       # exception line closes the block
                continue
            in_traceback = False
        cut = index + 1                    # the job produced output again after crashing
    kept = "\n".join(lines[min(cut, floor):])
    # splitlines() drops the final separator; keep it so an unnarrowed body round-trips.
    return kept + "\n" if kept and body.endswith("\n") else kept


def _read_tail(path, limit=None):
    """Read at most the last <limit> bytes; .err files here reach 15MB."""
    limit = TAIL_BYTES if limit is None else limit
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > limit:
                f.seek(size - limit)
            return f.read().decode("utf-8", "replace")
    except OSError:
        return ""


def scan(log_dir=None, window_hours=None):
    """Scan every *.err and return per-job crash statistics. Never raises."""
    directory = log_dir or _log_dir()
    window = (window_hours if window_hours is not None else WINDOW_HOURS) * 3600
    now = time.time()
    jobs = {}
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".err"))
    except OSError:
        return jobs
    for name in names:
        err_path = os.path.join(directory, name)
        try:
            err_mtime = os.path.getmtime(err_path)
        except OSError:
            continue
        if window > 0 and (now - err_mtime) > window:
            continue  # this job has not crashed recently; nothing live to alert on
        job = name[:-4]
        body = _read_tail(err_path)
        if RECENCY_GATE:
            body = live_tail(body)
        tracebacks = parse_tracebacks(body)
        if not tracebacks:
            continue
        log_path = os.path.join(directory, job + ".log")
        try:
            log_size = os.path.getsize(log_path)
            log_mtime = os.path.getmtime(log_path)
        except OSError:
            log_size, log_mtime = 0, 0.0
        by_sig = {}
        for tb in tracebacks:
            entry = by_sig.setdefault(tb["signature"], {"count": 0, **tb})
            entry["count"] += 1
        # No successful output at all, or output that stopped long before the crashes started:
        # every invocation of this module is failing. This is the preflight_gate case.
        dead = (len(tracebacks) >= DEAD_MIN_ATTEMPTS
                and (log_size == 0 or (err_mtime - log_mtime) > STALE_LOG_S))
        jobs[job] = {"job": job, "err_path": err_path, "tracebacks": len(tracebacks),
                     "err_mtime": err_mtime, "log_size": log_size, "log_mtime": log_mtime,
                     "module_dead": dead, "signatures": by_sig}
    return jobs


def classify(jobs):
    """Turn raw counts into fireable findings, most severe first."""
    findings = []
    for job, info in jobs.items():
        total = info["tracebacks"] or 1
        for sig, entry in info["signatures"].items():
            count = entry["count"]
            share = count / float(total)
            reasons = []
            # A dead module makes ALL of its signatures critical, but a signature seen twice is
            # not the reason the module is dead — require it to be a real share of the failures.
            if info["module_dead"] and (count >= DEAD_MIN_ATTEMPTS or share >= DOMINANCE):
                reasons.append("module_dead")
            if count > MIN_HITS:
                reasons.append("repeating")
            if total >= DOMINANCE_MIN and share >= DOMINANCE:
                reasons.append("dominant")
            if not reasons:
                continue
            transient = bool(_TRANSIENT.search(entry["exception"]))
            if transient and not ("module_dead" in reasons and share >= DOMINANCE):
                continue  # infrastructure weather; the job still succeeds between blips
            findings.append({
                "job": job, "signature": sig, "count": count, "share": round(share, 4),
                "job_tracebacks": total, "reasons": reasons, "transient": transient,
                "severity": "critical" if "module_dead" in reasons else "high",
                "exception": entry["exception"], "last_frame": entry["last_frame"],
                "traceback": entry["body"], "err_path": info["err_path"],
                "log_size": info["log_size"],
            })
    # Rank by blast radius, not by label alone: a 100%-dead module is weighted 3x, but a
    # 10,000-hit crash loop at 98.9% must not be buried under a 46-hit dead-module signature.
    findings.sort(key=lambda f: -f["count"] * (3 if "module_dead" in f["reasons"] else 1))
    return findings


def coalesce_by_signature(findings):
    """Collapse findings that share a signature into one, naming every affected job.

    One module-level failure crashes every scheduled job at once, because they all
    import the same module before any job body runs. Firing per JOB turned a single
    `NameError: name 'run_editorial' is not defined` into TWENTY-ONE queued tasks
    (measured: 33 tasks under one detector fingerprint, in just 3 traceback groups
    of 21, 10 and 2). Each one costs an agent a full run to reach the same
    conclusion about the same already-fixed line.

    Per-SIGNATURE dedupe alone is not the answer either, and `state_key` below
    records why it was abandoned: with a job+signature slug, the first job wrote
    state[sig] and every other job's identical signature was suppressed, so genuinely
    broken jobs went unreported.

    This keeps both properties. One task per signature — and it LISTS every job the
    signature killed, so nothing is suppressed; the jobs are in the body instead of
    in separate tickets. A signature affecting a single job produces the same
    single-job task it always did.

    Order is preserved from `classify`, which has already ranked by blast radius.
    """
    merged = {}
    order = []
    for f in findings or []:
        sig = f.get("signature")
        first = sig not in merged
        if first:
            merged[sig] = dict(f)
            merged[sig]["jobs"] = []
            order.append(sig)
        m = merged[sig]
        m["jobs"].append({
            "job": f.get("job"), "count": f.get("count", 0), "share": f.get("share", 0),
            "err_path": f.get("err_path"), "reasons": list(f.get("reasons") or []),
        })
        # `first` rather than an identity check: `dict(f)` above is a COPY, so
        # `f is not merged[sig]` is true even for the finding that seeded the group
        # and its count was added twice.
        if not first:
            m["count"] = m.get("count", 0) + f.get("count", 0)
            # Worst case wins: one dead module among many crash-loopers is still a
            # dead module, and downgrading it because a sibling was merely repeating
            # would hide the more serious of the two.
            for r in (f.get("reasons") or []):
                if r not in m["reasons"]:
                    m["reasons"].append(r)
            if f.get("severity") == "critical":
                m["severity"] = "critical"
    out = []
    for sig in order:
        m = merged[sig]
        # The representative job is the worst-hit one; the rest are listed in the body.
        m["jobs"].sort(key=lambda j: -j.get("count", 0))
        m["job"] = m["jobs"][0]["job"]
        m["err_path"] = m["jobs"][0]["err_path"]
        m["job_count"] = len(m["jobs"])
        out.append(m)
    return out


def state_key(finding):
    """The dedupe key for one finding: JOB **and** signature.

    This used to be the signature alone, while _file_task's slug was job+signature. One
    NameError shape ('run_editorial' is not defined) crashes eleven different jobs, so firing
    for the first job wrote state[sig] and every OTHER job's identical signature was then
    reported '[deduplicated]' forever — 26 of 49 live findings, including 2 of the 3 CRITICAL
    100%-dead modules (cost-intelligence, credresolver), could never file a task. The bot
    watching the bots was itself silent.
    """
    # Signature-only again, but ONLY because findings are coalesced by signature
    # before they get here (see coalesce_by_signature): the single task names every
    # affected job, so dedupe can no longer suppress a job into silence. The
    # job+signature key remains correct for any caller that skips coalescing, which
    # is why the job is still in the key when a finding carries no `jobs` list.
    if finding.get("jobs"):
        return finding.get("signature", "")
    return "%s|%s" % (finding.get("job", ""), finding.get("signature", ""))


def _should_fire(finding, state, now):
    """Dedupe by (job, signature): fire once, then after a cooldown or a 10x escalation."""
    prior = state.get(state_key(finding))
    # Migration: entries written before the key carried the job. Honour them once so upgrading
    # does not replay every historical alert, but only for the job that actually recorded it.
    if not prior:
        legacy = state.get(finding["signature"])
        if legacy and legacy.get("job") == finding["job"]:
            prior = legacy
    # Migration the other way, for coalesced findings: this signature was previously
    # tracked as one "<job>|<signature>" entry PER JOB. Without this, the first run
    # after coalescing looks brand new and re-alerts every signature at once — the
    # noise the coalescing exists to remove. The most recent per-job entry stands in
    # for the group, because any one of them firing means the group was already seen.
    if not prior and finding.get("jobs"):
        candidates = [state.get("%s|%s" % (j.get("job", ""), finding.get("signature", "")))
                      for j in finding["jobs"]]
        candidates = [c for c in candidates if c]
        if candidates:
            prior = max(candidates, key=lambda c: float(c.get("last_alert") or 0))
    if not prior:
        return True, "new"
    if (now - float(prior.get("last_alert") or 0)) >= COOLDOWN_S:
        return True, "cooldown elapsed"
    if finding["count"] >= float(prior.get("count_at_alert") or 0) * ESCALATION:
        return True, "escalated %dx" % ESCALATION
    return False, "deduplicated"


def _orchestrator_project():
    """The project row that owns the runner itself, so remediation tasks land somewhere real."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        for row in (db.select("projects", {"select": "id,name,repo_path"}) or []):
            if os.path.abspath(row.get("repo_path") or "") == os.path.abspath(root):
                return row
    except (OSError, TypeError, ValueError):
        pass
    return {}


def _file_task(finding, project_row, filer):
    """Turn one finding into remediation work. Dedupe is the DB; the budget is the filer."""
    if not FILE_TASKS:
        return "disabled"
    jobs = finding.get("jobs") or [{"job": finding["job"], "count": finding.get("count", 0),
                                    "share": finding.get("share", 0),
                                    "err_path": finding.get("err_path")}]
    # One slug per SIGNATURE when the failure spans jobs, so a shared root cause is one
    # task rather than one per job. A single-job signature keeps the old job-based slug,
    # so existing tasks and their dedupe state stay addressable.
    slug = (guard_tasks.stable_slug("crashloop", "sig", finding["signature"][:8])
            if len(jobs) > 1
            else guard_tasks.stable_slug("crashloop", finding["job"], finding["signature"][:8]))
    affected = ("".join("  - %s: %d occurrence(s) in %s\n" % (j["job"], j["count"], j["err_path"])
                        for j in jobs))
    spans = ("This ONE failure is killing %d scheduled jobs. They share a signature, so "
             "they share a cause — fix it once.\n\nAffected jobs:\n%s\n"
             % (len(jobs), affected)) if len(jobs) > 1 else ""
    severity = guard_tasks.CRITICAL if "module_dead" in finding["reasons"] else guard_tasks.HIGH
    return filer.file(
        project_row.get("id"), slug,
        (("A scheduled job is in a CRASH LOOP and has been failing silently.\n\n" + spans) +
                       "job: %s\nlog: %s\noccurrences: %d (%.0f%% of this job's tracebacks)\n"
                       "why it fired: %s\n%s\n"
                       "Fix the root cause, then confirm the job actually runs "
                       "(`python3 runner/periodic.py %s` or the module's own entry point) and that "
                       "no new traceback appears in %s.\n\nTraceback:\n%s"
                       % (finding["job"], finding["err_path"], finding["count"],
                          finding["share"] * 100, ", ".join(finding["reasons"]),
                          ("NOTE: zero successful runs detected — this module is 100% dead.\n"
                           if "module_dead" in finding["reasons"] else ""),
                          finding["job"].replace("-", "_"), finding["err_path"],
                          finding["traceback"])),
        severity=severity, project_name="ORCHESTRATOR",
        title=("%d jobs are %s — %s x%d" % (len(jobs),
                                            "100%% DEAD" if severity == guard_tasks.CRITICAL
                                            else "crash-looping",
                                            finding["exception"][:100], finding["count"])
               if len(jobs) > 1 else
               "%s is %s — %s x%d" % (finding["job"],
                                     "100%% DEAD" if severity == guard_tasks.CRITICAL
                                     else "crash-looping",
                                     finding["exception"][:100], finding["count"])),
        escalate_why=("%d identical tracebacks in %s. Last frame: %s."
                      % (finding["count"], finding["err_path"], finding["last_frame"])))


def _alert(finding):
    """A crash loop must be loud: notification + an approvals card, not a log line."""
    headline = ("crash_loop_detector: %s is %s — %s x%d (%s)"
                % (finding["job"],
                   "100% DEAD" if "module_dead" in finding["reasons"] else "crash-looping",
                   finding["exception"][:120], finding["count"], ", ".join(finding["reasons"])))
    try:
        import notify
        notify.send(headline)
    except (ImportError, OSError, TypeError):
        pass
    try:
        db.insert("approvals", {
            "project": "ORCHESTRATOR", "kind": "self", "status": "pending",
            "title": headline[:200],
            "why": ("%d identical tracebacks in %s. Last frame: %s."
                    % (finding["count"], finding["err_path"], finding["last_frame"]))[:1000],
            "value": "A silently dead scheduled job is unbounded invisible loss; this is the "
                     "preflight_gate 19-day failure mode.",
            "risk": finding["traceback"][:1500],
        })
    except (KeyError, TypeError, ValueError) as e:
        _log_event({"event": "approval_error", "job": finding["job"], "error": str(e)})


def run(log_dir=None, window_hours=None, dry_run=False):
    """Scan, classify, dedupe, alert and file remediation tasks. Never raises."""
    if not ENABLED:
        print("crash_loop_detector: disabled")
        return {"enabled": False}
    jobs = scan(log_dir, window_hours)
    findings = coalesce_by_signature(classify(jobs))
    state = _load_state()
    now = time.time()
    project_row = _orchestrator_project() if not dry_run else {}
    filer = guard_tasks.Filer(NAME, max_per_run=MAX_TASKS_PER_RUN, enabled=not dry_run)
    summary = {"jobs_scanned": len(jobs), "findings": len(findings), "fired": 0,
               "deduplicated": 0, "throttled": 0, "dead_modules": 0}
    for finding in findings:
        if "module_dead" in finding["reasons"]:
            summary["dead_modules"] += 1
        fire, why = _should_fire(finding, state, now)
        # An alert storm is just a different kind of silence. Fire the worst few per cycle; the
        # rest keep their place in the ranking and fire on a later cycle once these are fixed.
        if fire and summary["fired"] >= MAX_FIRES:
            fire, why = False, "throttled (>%d fires this cycle)" % MAX_FIRES
            summary["throttled"] += 1
        print("  %-26s %-8s x%-6d %5.1f%%  %s%s"
              % (finding["job"], finding["severity"], finding["count"], finding["share"] * 100,
                 finding["exception"][:80], "" if fire else "  [%s]" % why), flush=True)
        if fire:
            _log_event({"event": "finding", "fire": True, "why": why,
                        **{k: v for k, v in finding.items() if k != "traceback"}})
        else:
            # Compact record for suppressed findings: at a 5-minute cadence with ~50 live
            # signatures, full records would add megabytes a day to .runtime/logs.
            _log_event({"event": "finding_suppressed", "job": finding["job"],
                        "signature": finding["signature"], "count": finding["count"], "why": why})
        # ALERTING is deduplicated; REMEDIATION is not. A finding that is still live but whose
        # alert is inside its cooldown must still have an open task — the alert cooldown exists
        # to stop notification spam, not to stop work from being created. The database (not the
        # cooldown) decides whether a task already exists, so this is idempotent by construction.
        if not dry_run:
            _file_task(finding, project_row, filer)
        if not fire:
            if why.startswith("deduplicated"):
                summary["deduplicated"] += 1
            continue
        summary["fired"] += 1
        if dry_run:
            continue
        _alert(finding)
        state[state_key(finding)] = {
            "job": finding["job"], "exception": finding["exception"][:200],
            "first_seen": (state.get(state_key(finding)) or {}).get("first_seen") or now,
            "last_alert": now, "count_at_alert": finding["count"], "reasons": finding["reasons"],
        }
    summary.update(filer.counters())
    if not dry_run:
        _save_state(state)
    _log_event({"event": "sweep", **summary})
    print("crash_loop_detector: %(jobs_scanned)d job log(s), %(findings)d finding(s), "
          "%(dead_modules)d dead module(s), %(fired)d fired, %(deduplicated)d deduped, "
          "%(throttled)d throttled" % summary)
    print("crash_loop_detector: " + filer.summary_line())
    return summary


def stats():
    """Module statistics for the dashboard."""
    try:
        findings = coalesce_by_signature(classify(scan()))
        return {"enabled": ENABLED, "findings": len(findings),
                "dead_modules": len([f for f in findings if "module_dead" in f["reasons"]]),
                "tracked_signatures": len(_load_state())}
    except (OSError, TypeError, ValueError):
        return {"enabled": ENABLED, "findings": 0, "dead_modules": 0, "tracked_signatures": 0}


if __name__ == "__main__":
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    directory = next((a for a in argv if not a.startswith("-")), None)
    window = None
    for a in argv:
        if a.startswith("--window-hours="):
            window = float(a.split("=", 1)[1])
    run(log_dir=directory, window_hours=window, dry_run=dry)
