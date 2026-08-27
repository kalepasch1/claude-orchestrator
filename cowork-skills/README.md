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
6. A zero-row claim is NOT proof of an empty queue. Count `QUEUED` separately from
   claimable; `queued > 0` with nothing claimable is a STALL and must never be reported
   as a clean run. From 2026-07-15 to 2026-08-27 all 16 executors reported success against
   a queue that never moved, because both cases returned zero rows.

## These invariants are enforced, not just documented

`runner/tests/test_cowork_skill_invariants.py` checks every file in this directory on
every test run, so a regression fails CI instead of quietly costing six weeks:

    python3 -m pytest runner/tests/test_cowork_skill_invariants.py

Invariant 6 was added to all 16 copies by `tools/patch_skill_claimability_preflight.py`
(idempotent; `--check` reports drift without writing).

**Sync direction for this change:** the fix landed here first, so the live copies at
`~/Documents/Claude/Scheduled/cowork-executor*/SKILL.md` are now BEHIND. Copy repo → live:

    for d in ~/Documents/Claude/Scheduled/cowork-executor*/; do
      cp cowork-skills/"$(basename "$d")".SKILL.md "$d/SKILL.md"
    done
