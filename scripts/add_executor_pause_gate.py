#!/usr/bin/env python3
"""Insert a kill-switch check into every cowork-executor skill, ahead of Step 1.

runner/db.py drops paused projects from its claim set (claim_task, "skip paused
projects") and runner/kill_switch.py is_paused() gates the runner on the global and
host scopes. The sixteen SKILL.md files never mention `controls` or `paused` at all, so
a scheduled cowork executor claims and pushes straight through a deliberate halt.

Live when this was written: a scope=global pause had been in force for three days
("executor outage 2026-08-24: every hosted provider is out of credit"), and all
sixteen portfolio projects carried their own project-scope pause -- one of them set by
the operator by name. Nothing in the skill would have stopped an executor.

Idempotent.
"""
import pathlib
import sys

SKILLS = pathlib.Path(__file__).resolve().parent.parent / "cowork-skills"

MARKER = "### 0c. Honour the kill switch"

GATE = """### 0c. Honour the kill switch (every loop, BEFORE claiming)

`runner/db.py` drops paused projects from its claim set and `runner/kill_switch.py`
`is_paused()` gates the runner on the global and host scopes. **This skill had no such
check**, so a scheduled executor would claim, commit and push straight through a
deliberate halt. Latest decision per scope wins, and `updated_by='remote-quarantine'`
rows do not count -- both mirror `is_paused()`.

```sql
SELECT scope, COALESCE(project,'-') AS project, reason, updated_at,
       now() - updated_at AS age
FROM (
  SELECT DISTINCT ON (scope, project) scope, project, paused, reason, updated_at
  FROM controls
  WHERE COALESCE(updated_by,'') <> 'remote-quarantine'
  ORDER BY scope, project, updated_at DESC
) latest
WHERE paused AND scope IN ('global','project')
ORDER BY scope, project;
```

- **A `global` row -> stop this run now.** Claim nothing, push nothing. Report the
  reason and its age and exit. A global pause is an operator decision about spend,
  provider credit or safety; it is not an obstacle to route around, and "the queue has
  work in it" is not a reason to override it.
- **A `project` row** -> that project is off limits for this run. Do not claim its
  tasks. If you already hold one, release it to QUEUED rather than leaving it RUNNING.
- **No rows** -> proceed to Step 1.

This gate outranks every "ZERO SKIP" and "never stop early" instruction below. Those
rules exist to stop an executor talking itself out of ordinary work; they were never
meant to override a kill switch.

---

"""


def patch(path: pathlib.Path) -> str:
    text = path.read_text()
    if MARKER in text:
        return "already current"
    anchor = "## Step 1"
    if anchor not in text:
        return "!! no Step 1 anchor"
    text = text.replace(anchor, GATE + anchor, 1)
    path.write_text(text)
    return "pause-gate inserted"


def main() -> int:
    files = sorted(SKILLS.glob("cowork-executor*.SKILL.md"))
    if not files:
        print(f"no skill files under {SKILLS}", file=sys.stderr)
        return 1
    bad = 0
    for f in files:
        mark = patch(f)
        if mark.startswith("!!"):
            bad += 1
        print(f"{f.name}: {mark}")
    print(f"\n{len(files)} file(s), {bad} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
