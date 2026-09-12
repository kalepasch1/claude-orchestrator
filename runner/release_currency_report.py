#!/usr/bin/env python3
"""release_currency_report — the human-inspectable half of the currency alarm.

WHY THIS EXISTS
---------------
`blocked_triage.release_currency_check()` is the alarm that fires when prod falls
behind the work that has been built: many unmerged `agent/*` heads AND a base
branch that has not advanced inside the window. It is a good alarm. It is also
write-only and negative-only, and that makes it useless for the one question an
operator actually asks before shipping:

    "is the fleet current RIGHT NOW?"

Three properties of the alarm make that question unanswerable from it:

  1. **It only speaks when something is wrong.** A clean fleet and a fleet the
     check never looked at produce the identical artifact: nothing. That is the
     same silence-as-success failure `merge_train_report` was written to end.
  2. **It self-limits to one scan per 6h.** An operator who runs it by hand
     within six hours of the scheduled scan gets `[]` back — which reads exactly
     like "all clear" and is not. The gate is correct for a 10-minute triage
     loop and wrong for a human at a terminal.
  3. **It discards the per-project detail for passing projects.** Findings carry
     only the projects over BOTH thresholds, so there is no way to see that a
     project sits at 24 branches against a limit of 25.

This module answers the question instead of raising the alarm. It performs the
same read-only measurement, ungated, and reports EVERY project with an explicit
status — so a pass is a positive statement rather than an absence.

RELATIONSHIP TO THE ALARM
-------------------------
Deliberately one-directional: this module imports the alarm's thresholds so the
two can never disagree about what "current" means, and it never calls
`release_currency_check()` and never writes `release_currency_scan` rows. Calling
it would consume the 6h gate and suppress the real alarm's next scheduled scan —
a report that silences the thing it reports on is worse than no report.

THE UNKNOWN STATUS
------------------
`release_currency_check()` turns unreadable git output into `age_h = -1`, which
can never exceed the threshold, so such a project is silently counted as current
no matter how many branches are waiting. That behaviour is pinned by
`test_release_currency_check.py` and changing it belongs in its own task — so
this module does not change it. It makes it VISIBLE: the same condition surfaces
here as `UNKNOWN` with the raw git output attached, rather than as a `PASS`. The
alarm's semantics are untouched; the operator simply stops being lied to.

USAGE
-----
    python3 runner/release_currency_report.py           # human table, exit 0/1
    python3 runner/release_currency_report.py --json    # machine-readable
    python3 runner/release_currency_report.py --strict  # UNKNOWN also fails

Exit codes: 0 = every project current, 1 = at least one project behind,
2 = a project could not be measured and --strict was given.

Never raises. A report that can break the release train is worse than no report.
"""

import json
import os
import subprocess
import sys
import time

RUNNER_DIR = os.path.dirname(os.path.abspath(__file__))
if RUNNER_DIR not in sys.path:
    sys.path.insert(0, RUNNER_DIR)

import db  # noqa: E402

#: Every project resolves to exactly one of these. There is no implicit fourth
#: state; `unaccounted()` exists to prove it.
PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"
SKIPPED = "SKIPPED"
STATUSES = (PASS, FAIL, UNKNOWN, SKIPPED)

#: Recorded once per release-train pass so currency at ship time is queryable
#: after the fact. Distinct from `release_currency_scan`, which is the alarm's
#: own 6h gate row and must not be written by this module.
REPORT_TASK_TYPE = "release_currency_report"

_LS_REMOTE_TIMEOUT_S = 60
_BASE_AGE_TIMEOUT_S = 30


def thresholds():
    """The alarm's thresholds, read live so the two can never drift apart.

    Imported lazily and defensively: `blocked_triage` pulls in the whole triage
    stack, and a report must not be the thing that fails to load. The fallbacks
    mirror the alarm's own env-var defaults.
    """
    try:
        import blocked_triage
        return (int(blocked_triage.RELEASE_CURRENCY_MAX_BRANCHES),
                int(blocked_triage.RELEASE_CURRENCY_MAX_MASTER_AGE_H))
    except Exception:
        return (int(os.environ.get("ORCH_RELEASE_CURRENCY_MAX_BRANCHES", "25")),
                int(os.environ.get("ORCH_RELEASE_CURRENCY_MAX_MASTER_AGE_H", "48")))


def count_agent_branches(text):
    """Unmerged built work = `refs/heads/agent/*` only.

    `master`, `release/*` and `dependabot/*` are not agent work and counting them
    would inflate the number the operator is asked to act on.
    """
    return sum(1 for line in (text or "").splitlines()
               if "refs/heads/agent/" in line)


def _measure(repo, base):
    """Read-only measurement of one repo. Returns (branches, age_h, raw, error).

    `age_h` is None when the base age could not be parsed — the caller turns that
    into UNKNOWN rather than into the alarm's silent -1.
    """
    heads = subprocess.run(["git", "ls-remote", "--heads", "origin"],
                           cwd=repo, capture_output=True, text=True,
                           timeout=_LS_REMOTE_TIMEOUT_S)
    branches = count_agent_branches(getattr(heads, "stdout", ""))
    age = subprocess.run(["git", "log", f"origin/{base}", "-1", "--format=%ct"],
                         cwd=repo, capture_output=True, text=True,
                         timeout=_BASE_AGE_TIMEOUT_S)
    raw = (getattr(age, "stdout", "") or "").strip()
    if not raw:
        return branches, None, raw, "base tip commit time was empty"
    try:
        age_h = (time.time() - float(raw)) / 3600.0
    except ValueError:
        return branches, None, raw, "base tip commit time was not a number"
    return branches, age_h, raw, None


def classify(branches, age_h, max_branches, max_age_h):
    """The AND, and only the AND.

    Both thresholds are strict (`>`, not `>=`) because the alarm's are, and a
    report that disagrees with the alarm about the boundary is a bug generator.
    """
    if age_h is None:
        return UNKNOWN
    if branches > max_branches and age_h > max_age_h:
        return FAIL
    return PASS


def evaluate(projects=None):
    """Measure every project. Read-only, ungated, never raises.

    Ungated is the point: this is what an operator runs by hand, and the alarm's
    6h self-limit would make a same-day second look indistinguishable from a
    clean fleet.
    """
    max_branches, max_age_h = thresholds()
    if projects is None:
        try:
            projects = db.select("projects",
                                 {"select": "name,repo_path,default_base"}) or []
        except Exception as exc:
            return [{"project": None, "status": SKIPPED,
                     "reason": f"project list unavailable: {type(exc).__name__}"}]
    rows = []
    for p in projects:
        name = p.get("name")
        base = p.get("default_base") or "master"
        row = {"project": name, "base": base, "status": SKIPPED,
               "max_branches": max_branches, "max_base_age_hours": max_age_h}
        try:
            repo = db.localize_repo_path(p.get("repo_path") or "")
            if not repo or not os.path.isdir(repo):
                row["reason"] = "repo not present on this machine"
                rows.append(row)
                continue
            branches, age_h, raw, err = _measure(repo, base)
            row["unmerged_agent_branches"] = branches
            row["status"] = classify(branches, age_h, max_branches, max_age_h)
            if age_h is None:
                row["base_age_hours"] = None
                row["reason"] = f"{err} (git said {raw!r})"
            else:
                row["base_age_hours"] = round(age_h, 1)
        except Exception as exc:
            row["status"] = SKIPPED
            row["reason"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        rows.append(row)
    return rows


def unaccounted(rows):
    """Any row that did not land in a known bucket.

    The contract is that every project resolves to exactly one status. If a
    future edit adds a silent path, it shows up as a number here instead of as
    silence.
    """
    return [r for r in rows if r.get("status") not in STATUSES]


def summarize(rows):
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        if r.get("status") in counts:
            counts[r["status"]] += 1
    return {"total": len(rows), "counts": counts,
            "behind": [r.get("project") for r in rows if r.get("status") == FAIL],
            "unmeasured": [r.get("project") for r in rows
                           if r.get("status") == UNKNOWN],
            "unaccounted": len(unaccounted(rows))}


def exit_code(rows, strict=False):
    """0 current, 1 behind, 2 unmeasurable-under---strict.

    FAIL outranks UNKNOWN: a project known to be behind is the more actionable
    signal, and collapsing the two would hide it.
    """
    statuses = {r.get("status") for r in rows}
    if FAIL in statuses:
        return 1
    if strict and UNKNOWN in statuses:
        return 2
    return 0


def _line(row):
    status = row.get("status", SKIPPED)
    name = row.get("project") or "(unnamed)"
    if status == PASS:
        return (f"  PASS     {name}: {row.get('unmerged_agent_branches')} unmerged "
                f"agent branches (limit {row.get('max_branches')}), base "
                f"{row.get('base_age_hours')}h old "
                f"(limit {row.get('max_base_age_hours')}h)")
    if status == FAIL:
        return (f"  FAIL     {name}: BEHIND — {row.get('unmerged_agent_branches')} "
                f"unmerged agent branches (limit {row.get('max_branches')}) and base "
                f"{row.get('base_age_hours')}h stale "
                f"(limit {row.get('max_base_age_hours')}h)")
    if status == UNKNOWN:
        return (f"  UNKNOWN  {name}: could not measure base age — "
                f"{row.get('reason')}; {row.get('unmerged_agent_branches')} agent "
                f"branches are waiting and currency cannot be confirmed")
    return f"  SKIPPED  {name}: {row.get('reason')}"


def render(rows, strict=False):
    """A verdict a human can read without knowing how the check works."""
    s = summarize(rows)
    out = ["release currency report — is production current with the work that is built?", ""]
    if rows:
        out.extend(_line(r) for r in rows)
    else:
        out.append("  (no projects to report)")
    out.append("")
    c = s["counts"]
    out.append(f"  {c[PASS]} current, {c[FAIL]} behind, "
               f"{c[UNKNOWN]} unmeasurable, {c[SKIPPED]} skipped "
               f"({s['total']} projects)")
    if s["behind"]:
        out.append("")
        out.append("VERDICT: FAIL — behind: " + ", ".join(str(p) for p in s["behind"]))
        out.append("  Action: run runner/catchup_drive.sh or inspect the merge train.")
    elif strict and s["unmeasured"]:
        out.append("")
        out.append("VERDICT: FAIL (--strict) — unmeasurable: "
                   + ", ".join(str(p) for p in s["unmeasured"]))
    else:
        out.append("")
        out.append("VERDICT: PASS — no project is behind its built work.")
        if s["unmeasured"]:
            out.append("  Caveat: unmeasurable: "
                       + ", ".join(str(p) for p in s["unmeasured"]))
    if s["unaccounted"]:
        out.append(f"  WARNING: {s['unaccounted']} project(s) in no known bucket.")
    return "\n".join(out)


def record(rows, source="manual"):
    """Persist one snapshot so currency at ship time stays queryable.

    Fail-soft and deliberately NOT a `release_currency_scan` row: writing that
    type would advance the alarm's 6h gate and suppress its next real scan.
    Returns True only if the row was actually written.
    """
    try:
        payload = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "source": source, "summary": summarize(rows), "projects": rows}
        db.insert("coordination_tasks",
                  {"task_type": REPORT_TASK_TYPE,
                   "payload": json.dumps(payload, default=str)[:8000]},
                  upsert=False)
        return True
    except Exception:
        return False


def gate(source="release_train", strict=False, echo=True):
    """One call for the release pipeline: measure, record, report, verdict.

    Returns `(ok, rows)`. Swallows everything — an instrumentation fault must
    never be the reason a release does not ship.
    """
    try:
        rows = evaluate()
        record(rows, source=source)
        if echo:
            for r in rows:
                if r.get("status") in (FAIL, UNKNOWN):
                    print(f"release_currency_report[{source}]:{_line(r).strip()}",
                          flush=True)
        return exit_code(rows, strict=strict) == 0, rows
    except Exception as exc:
        print(f"release_currency_report: report failed ({type(exc).__name__}); "
              f"not blocking the release", flush=True)
        return True, []


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    strict = "--strict" in argv
    quiet = "--quiet" in argv
    persist = "--record" in argv
    rows = evaluate()
    if persist:
        record(rows, source="cli")
    if not quiet:
        print(json.dumps({"summary": summarize(rows), "projects": rows},
                         indent=2, default=str) if as_json else render(rows, strict))
    return exit_code(rows, strict=strict)


if __name__ == "__main__":
    sys.exit(main())
