#!/usr/bin/env python3
"""One-shot editor: bring the cowork-executor skills' claim step in line with runner/db.py.

The Python claim path (runner/db.py _done_slugs + why_no_claim) and the claim RPC
(runner/migrations/001_claim_next_rpc.sql) were both corrected on 2026-08-25. The
sixteen cowork-executor SKILL.md files carry their own copy of the claim SQL and were
not updated with them, so every scheduled executor still runs the pre-fix predicate and
still maps "0 rows" to "queue empty".

Idempotent: running twice is a no-op. Reports per-file what it changed.
"""
import pathlib
import sys

SKILLS = pathlib.Path(__file__).resolve().parent.parent / "cowork-skills"

OLD_PREDICATE = """    AND (t.deps IS NULL OR array_length(t.deps,1) IS NULL
         OR NOT EXISTS (
           SELECT 1 FROM unnest(t.deps) AS dep
           WHERE dep NOT IN (
             SELECT t2.slug FROM tasks t2
             WHERE t2.project_id = t.project_id AND t2.state IN ('DONE','MERGED')
           )
         ))"""

NEW_PREDICATE = """    -- Dependency gate. Mirrors runner/db.py _done_slugs() and
    -- runner/migrations/001_claim_next_rpc.sql, both corrected 2026-08-25; this
    -- third copy of the predicate was not updated with them and had drifted behind.
    --
    --  * DEPLOYED_AND_VERIFIED is strictly stronger than DONE -- shipped and
    --    verified in production -- and was treated as a blocker, so a dependent of
    --    fully delivered work was held back by its own success.
    --  * A dep may be written `project_name:slug` (pareto-2080 tasks depend on
    --    `beethoven:...` this way). Matched only inside t.project_id, a qualified
    --    dep can never resolve, making those tasks unclaimable by construction.
    --  * `dep NOT IN (SELECT t2.slug ...)` is three-valued: one NULL slug in the
    --    candidate set makes the comparison NULL rather than TRUE for every dep,
    --    which filters the row out and reports ALL dependencies satisfied. That is
    --    fail-OPEN -- it would claim tasks whose deps are unmet. There are no NULL
    --    slugs today, so this is latent rather than active, but NOT EXISTS closes
    --    the hole outright.
    AND (t.deps IS NULL OR array_length(t.deps,1) IS NULL
         OR NOT EXISTS (
           SELECT 1 FROM unnest(t.deps) AS dep
           WHERE NOT EXISTS (
             SELECT 1 FROM tasks t2
             LEFT JOIN projects p2 ON p2.id = t2.project_id
             WHERE t2.state IN ('DONE','MERGED','DEPLOYED_AND_VERIFIED')
               AND ((position(':' in dep) = 0
                     AND t2.project_id = t.project_id AND t2.slug = dep)
                 OR (position(':' in dep) > 0
                     AND p2.name = split_part(dep, ':', 1)
                     AND t2.slug = split_part(dep, ':', 2)))
           )
         ))"""

STALL_BLOCK = """**0 rows does NOT mean the queue is empty.** It means nothing was *claimable*, and
that has two very different causes which produce the identical signal. Tell them apart
before doing anything else:

```sql
SELECT count(*) AS queued_remaining
FROM tasks WHERE state='QUEUED' AND kind NOT IN ('speculative');
```

- **`queued_remaining = 0`** -> the queue really is empty. Heartbeat (Step 4), write
  `<run-summary>`, stop. This is the only successful exit.
- **`queued_remaining > 0`** -> the queue is **STALLED**, not finished. Treat this as an
  alert and never as a success exit. Run `python3 runner/queue_deadlock_report.py` in
  the beethoven repo, report which tasks are unclaimable and under which category
  (decomposed-childless / collapsed / terminal / dangling), and stop. Do **not** report
  a clean run, and do **not** bulk-clear deps to force the queue open -- three of the
  four categories need an operator decision about intent, and unblocking a task whose
  prerequisite never happened is the most expensive failure this fleet has.

Between 2026-07-15 and 2026-08-25 every executor took the first path against a queue of
327 tasks that had not moved in six weeks, and reported success each time. See
`QUEUE-DEADLOCK-2026-08-25.md`."""

OLD_EXIT_LINES = [
    "If 0 rows → heartbeat (Step 4), write `<run-summary>`, stop. **This is the ONLY exit condition.**",
    "If 0 rows → heartbeat (Step 4), stop.",
]


def patch(path: pathlib.Path) -> list[str]:
    text = original = path.read_text()
    changed = []

    if OLD_PREDICATE in text:
        text = text.replace(OLD_PREDICATE, NEW_PREDICATE)
        changed.append("dep-predicate")
    elif NEW_PREDICATE not in text:
        changed.append("!! dep-predicate NOT FOUND")

    if STALL_BLOCK in text:
        pass  # already patched
    else:
        for old in OLD_EXIT_LINES:
            if old in text:
                text = text.replace(old, STALL_BLOCK)
                changed.append("stall-detection (replaced exit line)")
                break
        else:
            # No explicit exit line: insert the block just before Step 2.
            for anchor in ("\n---\n\n## Step 2", "\n## Step 2"):
                if anchor in text:
                    text = text.replace(anchor, "\n" + STALL_BLOCK + "\n" + anchor, 1)
                    changed.append("stall-detection (inserted before Step 2)")
                    break
            else:
                changed.append("!! no Step 2 anchor")

    if text != original:
        path.write_text(text)
    return changed


def main() -> int:
    files = sorted(SKILLS.glob("cowork-executor*.SKILL.md"))
    if not files:
        print(f"no skill files under {SKILLS}", file=sys.stderr)
        return 1
    bad = 0
    for f in files:
        marks = patch(f)
        if any(m.startswith("!!") for m in marks):
            bad += 1
        print(f"{f.name}: {', '.join(marks) if marks else 'already current'}")
    print(f"\n{len(files)} file(s), {bad} with problems")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
