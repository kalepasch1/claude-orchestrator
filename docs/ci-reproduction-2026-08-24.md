# CI reproduction — `improve-improved-ci-cd-pipeline-integration-slice-1`

**Verified against:** `origin/master@5c4eaf2f5620aa6e263de622869f217a437190f9`
**Date:** 2026-08-24
**Scope:** inspection and reproduction only. No production code was changed by this task.

## Headline

**CI is red on `master` right now.** The `darwin-kernel — test + typecheck` job's
Typecheck step exits 2. It is not a flake, not environmental, and not caused by any
change this task made: `HEAD == origin/master` and `git status --porcelain --
packages/darwin-kernel` was empty when the command ran.

The three `runner-guards` steps and the `darwin-kernel` test step all pass.

## The `9b700345d3ea` premise does not hold

The task asked to find files referencing `PATCH TEMPLATE 9b700345d3ea` or a slug
implied by `patch-template-improve-automated-branch-management-system`.

`git grep 9b700345d3ea origin/master` returns nothing. The identifier exists only in
the queue row's own prompt text — it is a task-generator fingerprint, not a repo
artifact. Any downstream task premised on "re-enable the patch template
`9b700345d3ea`" is premised on something that was never in the tree, and should be
re-scoped or closed rather than attempted.

## How CI is actually triggered

`.github/workflows/ci.yml`, on `push` to `master`, on `pull_request`, and on
`workflow_dispatch`. Three jobs:

| Job | Steps | Status locally |
|---|---|---|
| `darwin-kernel` | `npm ci` → `node --test --experimental-strip-types test/*.test.ts` → `npx tsc --noEmit` | **tests pass, typecheck FAILS** |
| `runner-guards` | `pytest tests/test_ci_offline.py` → `compileall runner/` → `compileall *.py` | all pass |
| `task-reconciliation` | `reconcile_task_files.py --check` | skipped without Supabase creds (by design) |

The `workflow_dispatch` trigger exists because auto-sync promotes `dev → master` with
`GITHUB_TOKEN`, whose pushes do not trigger workflows — so `master` can move with no CI
run attached. That is very likely how this typecheck failure reached `master` unnoticed.

## Reproduction — exact CI command lines

### `runner-guards` — all three steps pass

```console
$ cd runner && SUPABASE_URL='' SUPABASE_SERVICE_KEY='' \
    python3 -m pytest tests/test_ci_offline.py -q --no-header
79 passed, 15 warnings in 2.54s

$ cd runner && python3 -m compileall -q . > /dev/null
rc=0

$ python3 -m compileall -q *.py > /dev/null
rc=0
```

### `darwin-kernel` — tests pass

```console
$ cd packages/darwin-kernel && node --test --experimental-strip-types test/*.test.ts
1..276
# tests 276
# suites 0
# pass 276
# fail 0
# cancelled 0
# skipped 0
# todo 0
# duration_ms 270.113375
```

### `darwin-kernel` — typecheck FAILS

```console
$ cd packages/darwin-kernel && npx tsc --noEmit
test/passport-attested-outcomes.test.ts(54,40): error TS2322: Type '"malicious_issuer"' is not assignable to type 'ProductId'.
test/spine-contracts.consumer.ts(26,8): error TS2307: Cannot find module '@spine/contracts' or its corresponding type declarations.
TSC_EXIT=2
```

## Root cause of each error

Both errors sit in `test/`, not `src/`, which is why 276 runtime tests pass while the
typecheck is red — `node --test --experimental-strip-types` strips types without
checking them. The runtime suite structurally cannot catch this class of error, so the
typecheck step is the only thing standing between a type regression and `master`, and
it is currently failing for reasons unrelated to any new work.

**TS2322 — `test/passport-attested-outcomes.test.ts:54`**

```ts
const tampered: Passport = {
  ...passport,
  claims: [{ ...passport.claims[0]!, issuer: 'malicious_issuer' }],
};
```

The test's whole point is that an invalid issuer must invalidate the attestation, but
`Passport.claims[].issuer` is typed as `ProductId` (a closed union in `src/types.ts`),
so the deliberately-bogus value cannot be assigned. The test is correct about the
behaviour it wants and wrong about how it expresses it in the type system. Fixing this
by widening `ProductId` would be the wrong repair — it would weaken a real constraint
to satisfy a test. The narrow fix is a localized cast at the tamper site with a comment
saying why, which is exactly the case `@ts-expect-error` with a reason exists for.

**TS2307 — `test/spine-contracts.consumer.ts:26`**

`@spine/contracts` resolves to nothing: there is no `paths` mapping in
`packages/darwin-kernel/tsconfig.json` and no such dependency in its `package.json`.
This is a consumer-contract test pointing at a package that is not wired into this
workspace.

Both files arrived in `cb4065c8` — *"chore: commit the in-flight tree, and declare
where the tests live"* — i.e. an in-flight tree was committed wholesale, and the
typecheck has been red since.

## What should happen next

This task was scoped to inspection, so nothing above was fixed. A follow-up bugfix task
has been queued (`bugfix-darwin-kernel-typecheck-red-on-master`) carrying this evidence.

Worth deciding separately: `master` currently accepts pushes whose CI never ran
(`GITHUB_TOKEN` promotions). Until that gap closes, "CI is green" is not a statement
anyone can make about `master` without dispatching the workflow by hand.
