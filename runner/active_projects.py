#!/usr/bin/env python3
"""Which projects the maintenance bots may spend money on.

WHY THIS EXISTS
---------------
`controls` rows with scope='project' and paused=true are how this fleet says "leave
this repo alone". merge_train honours it, the claim path honours it, release_train
honours it. Measured 2026-09-02: of the 131 modules under runner/ that select from
`projects`, exactly 10 read that flag. The other 121 treat a paused project as an
ordinary one.

For a reporting bot that is harmless. For the bots that touch the DISK it is not.
Caught live on this host at 18:19Z:

    pid 26080  61.8% CPU  3.45 GB RSS
        node /Users/kpasch/Documents/_ARCHIVED-apparently-do-not-use/
             node_modules/.bin/nuxt build
        parent: pid 77316  runner/build_daemon.py

build_daemon was running `git fetch`, `npm install` and a full production build,
every 600 seconds, against a directory whose name is literally
"_ARCHIVED-apparently-do-not-use" -- one of four archived repos that were paused on
2026-09-01 precisely so the fleet would stop touching them. Five of the fleet's
sixteen projects are paused; the daemon was warming all five.

The pause reasons say what these repos are:
    apparently-archived   "archived/superseded 2026-09-01 ... no controls row
                           existed, so merge_train treated these as ACTIVE"
    beethoven             "controlled fleet verification 2026-08-24 ... REVERSIBLE"

DESIGN
------
One helper, not 121 patches. Bots that spend real resources per repo call
`active(projects)` (or `paused_names()`) and skip the rest; the reporting bots can
keep seeing everything, because reading a row is free.

FAILS OPEN. A control-plane read that errors returns "nothing is paused", so a
Supabase outage can never quietly stop the fleet from maintaining its live repos.
The cost of failing open is one wasted sweep; the cost of failing closed is a fleet
that stops warming every repo it owns the moment the DB blinks.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def enabled():
    """Honouring the pause flag can be turned off, for one bad control row."""
    return os.environ.get("ORCH_MAINTENANCE_SKIPS_PAUSED", "true").strip().lower() \
        not in ("0", "false", "no", "off")


def paused_names(db=None):
    """Set of paused project names. Empty on any error -- see FAILS OPEN above."""
    if not enabled():
        return set()
    try:
        client = db
        if client is None:
            import db as _db_module
            client = _db_module
        rows = client.select("controls", {"select": "project,paused,scope",
                                          "scope": "eq.project", "paused": "is.true"}) or []
    except Exception:
        return set()
    out = set()
    for row in rows:
        name = (row.get("project") or "").strip()
        if name:
            out.add(name)
    return out


def active(projects, db=None):
    """Filter project rows down to the ones a maintenance bot may work on.

    Accepts the list shape `db.select("projects", ...)` returns. Rows with no name
    are KEPT: an unnamed row cannot match a pause control, and dropping it would be
    this helper inventing a policy nobody wrote.
    """
    paused = paused_names(db)
    if not paused:
        return list(projects or [])
    return [p for p in (projects or [])
            if (p.get("name") or "").strip() not in paused]


def skipped(projects, db=None):
    """The complement of active(), for the one log line that says what was skipped."""
    paused = paused_names(db)
    if not paused:
        return []
    return [p for p in (projects or [])
            if (p.get("name") or "").strip() in paused]


def note(projects, db=None):
    """A short, printable summary, or "" when nothing was skipped."""
    rows = skipped(projects, db)
    if not rows:
        return ""
    names = sorted((p.get("name") or "?") for p in rows)
    return "skipping %d paused project(s): %s" % (len(names), ", ".join(names))
