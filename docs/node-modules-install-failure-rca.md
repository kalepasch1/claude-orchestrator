# Root cause: `node_modules` installation failures in agent worktrees

**Task:** `backlog-batch-beethoven-a86bb21-recover-remaining--slice-5-identify-root-cause-n`
**Date:** 2026-08-06
**Scope:** identification only. No implementation — that is the next slice.

---

## Verdict

**Failure type: toolchain configuration.**

Specifically: dependency warming for a fresh worktree is implemented in exactly one
place — the shell helper — and the Python code paths that also create worktrees do not
do it. A worktree created by those paths has no `node_modules`, no `.nuxt`, and no
untracked env file, so the first command an agent runs there fails.

It is **not** any of the other three candidates:

| Candidate | Ruled out because |
|---|---|
| Version incompatibility (Node/npm mismatch) | The same `npm`/`node` binaries succeed in the main checkout on the same machine, in the same shell, minutes apart. The failure follows the *directory*, not the toolchain. |
| Lock file corruption | `package-lock.json` is tracked and identical in worktree and main checkout (a worktree is a checkout of the same commit). A corrupt lock would fail in the main checkout too. It does not. |
| Missing/incorrect dependency declaration | Same argument: `package.json` is tracked and byte-identical. Installs succeed in the main checkout from that manifest. |

The distinguishing evidence is that **the identical tree at the identical commit works in
one directory and fails in another**. That isolates the cause to per-directory setup, i.e.
configuration of the worktree creation path — not to versions, manifests, or lock state.

---

## Suspect locations

### 1. Warming exists only in the shell path — the primary cause

`runner/setup-worktrees.sh` does the right thing (lines ~79–99):

- symlinks `node_modules`, `.next/cache`, `node_modules/.cache` from the main checkout
  when `ORCH_WARM_DEPS != false` (zero-copy, zero disk);
- deliberately does **not** share `.nuxt` (generated files embed absolute paths);
- runs `npx nuxi prepare` in the worktree when `ORCH_NUXT_PREPARE != false`, to
  regenerate the worktree-specific type stubs.

The Python worktree creators do none of it. Verified by grep for
`node_modules` / `ORCH_WARM_DEPS` / `dependency_prewarm` / `nuxi prepare`:

| Creator | Warms deps? |
|---|---|
| `runner/setup-worktrees.sh` | yes |
| `runner/integration_runtime.py:341,373` | **no** (only mentions `node_modules` in an ignore list, line 28) |
| `runner/improvement_verify.py:245` | **no** — no matches at all |
| `runner/queue_elimination.py:175` | **no** — no matches at all |

Any worktree produced by those three starts cold.

### 2. `tsconfig.json` extends generated, gitignored output

Both Nuxt apps do this:

```json
{ "extends": "./.nuxt/tsconfig.json" }
```

`tomorrow/tsconfig.json:3`, `smarter/tsconfig.json:2`. `.nuxt/` is gitignored, so it is
absent from every fresh worktree. Consequences, both observed:

- `TSConfckParseError: … .nuxt/tsconfig.app.json … ENOENT` (already documented in
  `apparently`'s `CLAUDE.md`);
- `TS2307: Cannot find module '~/server/utils/…'` — the `~` path alias lives in that
  generated file, so alias resolution silently dies with it. This is the whole content of
  `dropbox-smarter-embeddable-core-apparently-pareto--slice-1`, which burned **ten
  attempts** chasing an import that was never broken.

### 3. The remedy is per-repo and inconsistent

`apparently` has `scripts/prepare-worktree.mjs` (idempotent, fail-soft, links
`node_modules` and `.nuxt`) and documents it in `CLAUDE.md` as the thing to run *instead
of* `npm install`. `tomorrow` and `smarter` have no such script — confirmed absent. So an
agent that has internalised the `apparently` convention runs
`node scripts/prepare-worktree.mjs` in `tomorrow`, gets `MODULE_NOT_FOUND`, and has no
documented fallback.

### 4. `toolchain_gate` reports the symptom correctly but cannot fix it

`runner/toolchain_gate.py:86–103` already knows that "build RED: npm not installed" is
usually missing `node_modules`, and records
`{"tool": "node_modules", "error": "dependencies not installed/warmed"}` after three
negative `dependency_prewarm.deps_ready()` probes. That diagnosis is accurate. It is
reporting, not repair — so the task keeps failing and keeps being requeued. This is why
the failure presents as a recurring `toolchain-repair` backlog rather than a one-off.

---

## Reproduction (three times this session, three different repos)

1. `git worktree add` in `tomorrow` → `npm test` → `ERR_MODULE_NOT_FOUND: vitest`.
   `node scripts/prepare-worktree.mjs` → `MODULE_NOT_FOUND` (script does not exist in
   this repo). Manual `ln -s ../../tomorrow/node_modules node_modules` → tests pass.
2. `git worktree add` in `smarter` → `tsc` → `TS2307` on a `~/` import that resolves
   fine in the main checkout. Same manual symlink → 21/21 tests pass.
3. `git worktree add` in `beethoven` → 7 tests fail with
   `RuntimeError: set SUPABASE_URL and SUPABASE_SERVICE_KEY`, because untracked
   `runner/.env` is not carried over. Symlinking it → 53/53 pass.

Case 3 is the same class of defect with a different untracked file, and worth fixing in
the same change: the warming step should carry the repo's untracked-but-required local
files, not just `node_modules`.

---

## Minimal change needed (for the implementation slice — not done here)

1. **Extract the warming step from `setup-worktrees.sh` into one reusable Python
   function** (e.g. `worktree_isolation.warm_worktree(repo_root, dest)`) that symlinks
   `node_modules` and the path-safe caches, runs `nuxi prepare` when the repo is Nuxt,
   and links the repo's untracked-but-required local files (`runner/.env`, `.env`).
   Idempotent and fail-soft, matching the shell version's semantics exactly.
2. **Call it from all three Python creators** — `integration_runtime.py` (both
   `worktree add` sites, 341 and 373), `improvement_verify.py:245`,
   `queue_elimination.py:175` — immediately after a successful `worktree add`.
3. **Stop depending on generated output for type resolution**: give each Nuxt repo's own
   `tsconfig.json` an explicit `paths` entry for `~/*` and `@/*` alongside the
   `.nuxt` extends, so alias resolution survives a missing `.nuxt`.
4. **Make the remedy uniform**: either add `scripts/prepare-worktree.mjs` to `tomorrow`
   and `smarter`, or drop it from `apparently` in favour of step 1 and update the three
   `CLAUDE.md` files together, so one documented command works everywhere.

**Acceptance for the implementation slice:** a worktree created by each of the three
Python paths can run that repo's test command with no manual setup. Step 1 is the whole
fix; steps 2–4 are what make it reachable.

---

## Note on this task's own framing

The prompt asks to compare against "the working patch template (ce2e8dcd7954)" and
"similar resolved cases". Neither is usable: `ce2e8dcd7954` resolves to a retrieval
template whose body is a hex id plus an `Intent:` token list with no diff, and the
"similar cases" are the sibling slices of the same auto-decomposed batch, which contain
the same boilerplate. The analysis above is therefore built on the repository and on
reproduced failures rather than on that template.
