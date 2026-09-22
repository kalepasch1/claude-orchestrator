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
6. Commits are authored `kalepasch1 <kalepasch@gmail.com>` — the canonical identity every
   repo's CLAUDE.md mandates and the release train's `author_identity_guard` enforces.
   All 16 skills said `user.name=` followed by the display name instead, so every executor
   produced commits the guard then REFUSED to push:

       author_identity_guard: name drift e69061a74340 'Kale Pasch' (canonical 'kalepasch1')
       author_identity_guard: REFUSED.
       error: failed to push some refs to 'https://github.com/kalepasch1/tomorrow.git'

   Sixteen executors, every run, generating work the release train could not ship — while
   the guard's own message named the correct value. `runner/tests/test_cowork_skill_git_identity.py`
   fails if it comes back.

   NOTE: these versioned copies and the live skills have drifted well beyond this line
   (a full live→backup sync is ~1,240 lines). That sync is its own task; it was not folded
   in here, because a one-line identity correction and an unreviewed bulk overwrite should
   not arrive in the same commit. Both sides were corrected in place instead.
