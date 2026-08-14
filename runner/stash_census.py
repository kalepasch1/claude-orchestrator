#!/usr/bin/env python3
"""stash_census.py — FLEET-WIDE stash census (audit addendum §C, operator 2026-07-30).

WHY THIS EXISTS
---------------
Two concurrent sessions measured the stash pile on "the repo" hours apart and disagreed:
one counted **592**, the other **315**, with `git reflog stash` on Mac 1 also showing 315
(i.e. no evidence of drops on Mac 1). The explanation that matters operationally is that a
stash pile is **per-checkout, per-machine**: Mac 2 (`Mandys-MacBook-Pro.local`) holds its own
independent pile, and *every* check the fleet runs — `sentinel.stash_drift_guard`,
`recover_stashes.sh`, the triage pass in the core integrity audit — runs against ONE machine's
local `.git` and is therefore blind to the other's. A ~277-stash delta could sit on Mac 2
indefinitely with nothing in any log to say so.

So this module makes the pile a FLEET observable instead of a local one:

  * every machine publishes its own census (count, reflog count, oldest entry, host, ts) into
    the shared `fleet_config` row `ORCH_STASH_CENSUS` (JSON keyed by hostname);
  * `reconcile()` reads all hosts back and answers the only question that matters before bulk
    triage begins: *are we looking at the whole pile?*
  * bulk triage is **gated**: `triage_blocked` stays True while any known host is missing or
    stale, or while a host's `git stash list` count disagrees with its `git reflog stash`
    count (the "drops happened / miscount" hypotheses).

DESIGN RULES (see CLAUDE.md)
  * Fail-soft everywhere — a census failure returns empty/default, never raises, never wedges
    the runner or sentinel.
  * READ-ONLY against git. This module never pops, applies, or drops a stash. Reconciliation
    remains a human/agent judgement call; this only makes the true denominator visible.
  * `ORCH_STASH_CENSUS` is a safe fleet_config key: no secret marker, ORCH_ prefixed.
"""
import datetime
import json
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CENSUS_KEY = "ORCH_STASH_CENSUS"
# A host that hasn't published within this window is treated as UNKNOWN, not as zero — the
# whole point of §C is that "invisible" must never be silently read as "empty".
CENSUS_STALE_S = int(os.environ.get("ORCH_STASH_CENSUS_STALE_S", "86400"))
# Hosts we always expect to hear from. Comma-separated; empty means "whoever has reported".
EXPECTED_HOSTS = tuple(
    h.strip() for h in os.environ.get("ORCH_STASH_CENSUS_HOSTS", "").split(",") if h.strip()
)

REPO_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _git(repo, *args, timeout=60):
    """Run git read-only in `repo`. Returns stdout string; "" on any failure."""
    try:
        r = subprocess.run(
            ("git",) + args,
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
        )
        if r.returncode != 0:
            return ""
        return r.stdout or ""
    except Exception:
        return ""


def _nonempty_lines(out):
    return [ln for ln in (out or "").splitlines() if ln.strip()]


def local_census(repo=None, host=None, runner=_git):
    """Read-only census of THIS machine's stash pile.

    `runner` is injectable so tests can exercise the parsing/discrepancy logic without a
    real repository. It is called as runner(repo, *git_args) and must return stdout text.

    Returns a dict; never raises.
    """
    repo = repo or REPO_DEFAULT
    host = host or socket.gethostname()
    try:
        stash_lines = _nonempty_lines(runner(repo, "stash", "list"))
        reflog_lines = _nonempty_lines(runner(repo, "reflog", "stash"))
        oldest = stash_lines[-1] if stash_lines else ""
        return {
            "host": host,
            "repo": repo,
            "count": len(stash_lines),
            "reflog_count": len(reflog_lines),
            "oldest": oldest[:200],
            "ts": _now().isoformat(),
        }
    except Exception:
        return {
            "host": host,
            "repo": repo,
            "count": 0,
            "reflog_count": 0,
            "oldest": "",
            "ts": _now().isoformat(),
            "error": "census failed",
        }


def _age_seconds(ts, now=None):
    """Seconds since ISO timestamp `ts`; None when unparseable."""
    if not ts:
        return None
    try:
        parsed = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return ((now or _now()) - parsed).total_seconds()


def reconcile(by_host, expected_hosts=EXPECTED_HOSTS, stale_s=CENSUS_STALE_S, now=None):
    """Turn per-host censuses into a fleet answer + a triage gate.

    `by_host` maps hostname -> census dict (as produced by local_census).

    Returns a report dict with:
      hosts            sorted hostnames that reported
      total            summed stash count across reporting, non-stale hosts
      per_host         {host: count} for reporting hosts
      missing_hosts    expected hosts that never reported
      stale_hosts      hosts whose census is older than stale_s
      drop_suspects    hosts where count != reflog_count (hypothesis 2: drops/expiry)
      triage_blocked   True while the pile is not fully accounted for
      reasons          human-readable list explaining the block

    Never raises.
    """
    report = {
        "hosts": [],
        "total": 0,
        "per_host": {},
        "missing_hosts": [],
        "stale_hosts": [],
        "drop_suspects": [],
        "triage_blocked": True,
        "reasons": [],
    }
    try:
        by_host = by_host or {}
        for host in sorted(by_host):
            entry = by_host.get(host) or {}
            if not isinstance(entry, dict):
                continue
            report["hosts"].append(host)
            count = int(entry.get("count") or 0)
            reflog = int(entry.get("reflog_count") or 0)
            age = _age_seconds(entry.get("ts"), now=now)
            if age is None or age > stale_s:
                report["stale_hosts"].append(host)
                continue
            report["per_host"][host] = count
            report["total"] += count
            if reflog and reflog != count:
                report["drop_suspects"].append(host)

        for host in expected_hosts or ():
            if host not in by_host:
                report["missing_hosts"].append(host)

        if not report["hosts"]:
            report["reasons"].append("no machine has published a stash census yet")
        if report["missing_hosts"]:
            report["reasons"].append(
                "no census from " + ", ".join(report["missing_hosts"])
                + " — its stash pile is invisible to every check run elsewhere"
            )
        if report["stale_hosts"]:
            report["reasons"].append(
                "stale census (>" + str(stale_s) + "s) from " + ", ".join(report["stale_hosts"])
            )
        if report["drop_suspects"]:
            report["reasons"].append(
                "stash list disagrees with reflog stash on "
                + ", ".join(report["drop_suspects"])
                + " — stashes were dropped or the reflog expired; explain before triaging"
            )
        report["triage_blocked"] = bool(report["reasons"])
    except Exception:
        report["reasons"] = ["reconcile failed"]
        report["triage_blocked"] = True
    return report


def _load_raw(dao=None):
    """Read the raw census map from fleet_config. Returns {} on any failure."""
    try:
        if dao is None:
            import fleet_config_dao as dao  # noqa: PLC0415 - optional/lazy, keeps this importable standalone
        row = dao.get(CENSUS_KEY) or {}
        raw = row.get("value") if isinstance(row, dict) else None
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def publish(census=None, dao=None, repo=None):
    """Merge THIS host's census into the shared fleet_config row. Fail-soft.

    Returns the merged map that was written ({} when the write could not happen).
    """
    try:
        census = census or local_census(repo=repo)
        host = census.get("host") or socket.gethostname()
        if dao is None:
            import fleet_config_dao as dao  # noqa: PLC0415
        merged = _load_raw(dao=dao)
        merged[host] = census
        dao.set_value(
            CENSUS_KEY,
            json.dumps(merged, sort_keys=True),
            note="fleet-wide stash census (audit addendum §C) — read-only, never pops/drops",
            updated_by=host,
        )
        return merged
    except Exception:
        return {}


def fleet_report(dao=None, expected_hosts=EXPECTED_HOSTS, stale_s=CENSUS_STALE_S):
    """Publish this host's census, then reconcile the whole fleet. Never raises."""
    try:
        merged = publish(dao=dao) or _load_raw(dao=dao)
        return reconcile(merged, expected_hosts=expected_hosts, stale_s=stale_s)
    except Exception:
        return reconcile({}, expected_hosts=expected_hosts, stale_s=stale_s)


def render(report):
    """Plain-text operator summary of a reconcile() report. Never raises."""
    try:
        lines = ["FLEET STASH CENSUS", "=" * 18]
        if report.get("per_host"):
            for host, count in sorted(report["per_host"].items()):
                lines.append(f"  {host:<32} {count:>5} stashes")
        else:
            lines.append("  (no fresh census from any machine)")
        lines.append(f"  {'TOTAL (accounted for)':<32} {report.get('total', 0):>5}")
        if report.get("triage_blocked"):
            lines.append("")
            lines.append("BULK TRIAGE BLOCKED — the pile is not fully accounted for:")
            for reason in report.get("reasons", []):
                lines.append(f"  - {reason}")
            lines.append("")
            lines.append("  Next step: run this on every machine (it publishes its own count),")
            lines.append("  then re-check. Do NOT begin bulk stash triage until this is clear.")
        else:
            lines.append("")
            lines.append("Every expected machine has reported a fresh, self-consistent count.")
            lines.append("Bulk triage may proceed against the TOTAL above.")
        return "\n".join(lines)
    except Exception:
        return "FLEET STASH CENSUS unavailable"


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    as_json = "--json" in argv
    local_only = "--local" in argv
    if local_only:
        report = reconcile({socket.gethostname(): local_census()})
    else:
        report = fleet_report()
    print(json.dumps(report, indent=2, sort_keys=True) if as_json else render(report))
    return 1 if report.get("triage_blocked") else 0


if __name__ == "__main__":
    sys.exit(main())
