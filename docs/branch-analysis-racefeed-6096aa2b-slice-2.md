# Branch analysis — `racefeed/agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2`

**Date:** 2026-08-11 · **Repo:** `/Users/kpasch/Documents/galop/racefeed`
**Tip commit:** `c4ecfd53ca7ba2dfb46b61b13598f342eae21232`
**Author:** kalepasch1 <kalepasch@gmail.com> · **Date:** Sun Aug 2 11:09:14 2026 -0400
**Status on mainline:** already an ancestor of `origin/master` (merged)

## Purpose

The slug says the branch repairs a `node_modules` install failure — it is the
`recover-missing-branch-` recovery of `toolchain-repair-6096aa2b-fix-node-modules-install-slice-2`,
raised after the original agent's branch went missing.

**It does not do that.** The branch is a *recovery-intent stub*: the placeholder
`patch_recovery.regenerate_from_intent()` writes when every real recovery route
(stored patch → reflog → cache replay) has already failed. Its stated purpose and
its contents do not match.

## Key changes

One commit, one new file, four added lines, zero deletions:

```
 .recovery-intent-recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2.txt | 4 ++++
 1 file changed, 4 insertions(+)
```

The file contains four keys and nothing else:

| Key | Value |
|---|---|
| `recovery-intent:` | `recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2` |
| `template:` | `59371fe244f5` |
| `intent:` | a bag of ~60 keywords (`056af630dd5f 07062319 … acceptance adapt agent branch build cache …`) |
| `base:` | `master` |

No `package.json`, no `package-lock.json`, no CI config, no install script, no
source file. Nothing that could affect a `node_modules` install was touched.

## Dependencies

- **Producer:** `runner/patch_recovery.py::regenerate_from_intent()` — the only
  writer of this file shape.
- **Upstream of it:** `runner/patch_templates.py::_ensure_branch()`, which calls
  `patch_recovery.recover()` and then falls back to `regenerate_from_intent()`.
- **Referenced template:** `59371fe244f5`, resolvable via
  `patch_templates.lookup()`.
- **Runtime dependencies introduced:** none. The branch adds no imports, no
  packages, no scripts. It cannot break a build and it cannot fix one.

## Finding

The stub is indistinguishable, to the merge train, from a genuine one-file
change. It was verified, merged, and the slug recorded as shipped. The
node-modules repair was never implemented, and the audit trail says otherwise.
Task `recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2`
is recorded `MERGED` with note *"already integrated, closed without rebuild"*.

This is not isolated. Scanning mainline history for the `recovery-intent-stub:`
subject:

| Repo | stub commits (all refs) | on mainline |
|---|---|---|
| racefeed | 41 | 27 |
| claude-orchestrator | 210 | 182 |
| apparently | 327 | 194 |
| tomorrow | 243 | 94 |
| pareto-2080 | 171 | 133 |
| **total** | **992** | **630** |

630 commits on mainline across five repos carry a recovery marker and no work.
Each corresponds to a task closed as done that shipped nothing.

## Remediation shipped with this analysis

`runner/recovery_stub_detector.py` — pure classification (no git, no DB, no
network) that tells a stub branch from a real one:

- `analyze_commit(subject, files, body)` → `real` / `stub` / `mixed` / `empty`
- `analyze_branch(commits)` → branch verdict plus `mergeable_as_work`
- `gate(commits)` → `(allow, reason)` for the merge train; blocks a stub-only
  branch so the slug stays open instead of closing as shipped
- `cleanup_paths(files)` → marker files safe to strip from a `mixed` branch
- `parse_git_log(text)` → parses `git log --format='%x00%s' --name-only`. The
  sentinel is required: git puts a blank line between subject and file list, so
  blank-line splitting drops every file name.

Verified against live data in this repo set:

```
$ git log --format='%x00%s' --name-only -1 \
    origin/agent/recover-missing-branch-toolchain-repair-6096aa2b-fix-node-modules-install-slice-2 \
    | python3 runner/recovery_stub_detector.py
stub: every commit only adds a recovery-intent marker (...); no work was done — do not record this slug as MERGED
$ echo $?
1

$ git log --format='%x00%s' --name-only -1 $(git log --no-merges --format=%H -1 origin/master) \
    | python3 runner/recovery_stub_detector.py
real: 1 substantive file(s) changed; no recovery-intent markers
$ echo $?
0
```

Tests: `runner/test_recovery_stub_detector.py`, 27 cases, green.

## Recommended follow-ups (not done here — out of this task's scope)

1. Call `recovery_stub_detector.gate()` from the merge train before recording a
   slug `MERGED`; on a `stub` verdict, requeue the slug rather than closing it.
2. Re-open the 630 mainline slugs whose only commit is a stub — starting with
   the node-modules install repair this branch was meant to be.
3. Have `regenerate_from_intent()` mark the branch it creates (branch name
   prefix or commit trailer) so the marker does not depend on file-shape sniffing.
