# Cowork executor skills — versioned backup

The live copies are at `~/Documents/Claude/Scheduled/cowork-executor*/SKILL.md`, which is
NOT under version control. They were silently broken for weeks with nothing to diff against
and no way to see when it happened — the 2026-08-02 credential purge removed the
`fleet_config` rows they depended on, and no one updated the 16 skills.

Copies are kept here so the next regression is visible in `git diff`. After editing a live
skill, re-run the sync:

    for d in ~/Documents/Claude/Scheduled/cowork-executor*/; do
      cp "$d/SKILL.md" cowork-skills/"$(basename "$d")".SKILL.md
    done

## Invariants these skills must preserve

1. NEVER read GITHUB_PAT / VERCEL_TOKEN / API keys from `fleet_config` — the rows are gone
   and a DB guard rejects re-adding them. git uses the osxkeychain helper; the vercel CLI is
   already logged in.
2. NEVER `git remote set-url origin` with an injected token. It corrupts the shared clone
   for the runner too.
3. Claim ordering puts operator-origin work (`dropbox-*` / `submitted_by`) FIRST.
4. `FOR UPDATE OF t SKIP LOCKED` — locking the joined `projects` row makes 16 concurrent
   executors skip each other's whole projects.
5. DONE only after a verified push of a non-doc diff. No stub commits, no DONE on push failure.
6. HONOUR THE KILL SWITCH before claiming. `runner/db.py` drops paused projects from its
   claim set via `kill_switch.is_paused()`; a skill whose claim SQL ignores `controls` will
   commit and push straight through a deliberate halt.

## Known divergence from `runner/db.py` (open)

The claim SQL in these skills resolves a dependency with:

    WHERE t2.state IN ('DONE','MERGED','DEPLOYED_AND_VERIFIED')

`runner/db.py::_done_slugs()` accepts that set **plus** the output of
`_closed_decompositions()` — a DECOMPOSED parent whose every child has finished, and (since
2026-09-09) one whose backlog-compactor collapse target has finished. A DECOMPOSED parent
never reaches DONE by design, so the skills are strictly stricter than the runner: an
executor refuses work the runner would take.

This is not theoretical. It is half of what deadlocked the operator drop-box — all 6 QUEUED
`dropbox-*` tasks sat at attempt=0 from 2026-08-07, and 5,015 of 5,316 DECOMPOSED parents
were childless when it was measured on 2026-09-09.

Closing it means teaching all 16 copies to also accept a parent whose children are all
finished, e.g. as an extra `OR EXISTS` arm on the dep check. Until that lands,
`tools/queue_health.py --assert-satisfiable` is the backstop: it fails loudly (exit 1) when
any QUEUED task depends on work that can never reach a satisfying state, instead of letting
the edge sit dead and unreported. Repair with:

    python3 tools/reconcile_childless_decompositions.py            # report
    python3 tools/reconcile_childless_decompositions.py --apply    # write
