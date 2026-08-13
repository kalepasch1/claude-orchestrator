# a86bb21 — register of collapsed tasks

Produced by `backlog-batch-beethoven-a86bb21-recover-remaining-stale-tasks-identify-and-fix-f`
(cowork-executor, 2026-08-13).

The parent `backlog-batch-beethoven-a86bb21` was recovered from the shelf and split into
four recovery streams. Three were handled:

| stream | disposition |
|---|---|
| `-recover-convention-conformance-lints` | handled (partly quarantined, see below) |
| `-recover-pinned-express-lane` | handled — `…-apply-fix-and-valida` is DONE with a commit |
| `-recover-economic-scheduler-revenue` | handled — four children DONE with commits |

The fourth, `-recover-remaining-stale-tasks`, is the subject of this register. Its own
children refer to "the first/second/third/fourth/fifth collapsed task" without ever
carrying the list they refer to — which is why several of them collapsed in turn. The
list is reconstructed below from the queue itself so no future task has to infer it.

## What "collapsed" means here

A task collapsed when it stopped being executable for a reason unrelated to its subject
matter. Four distinct mechanisms appear in this family, and they need different
remedies:

1. **Spec-lost** — the prompt was overwritten with a `Complete the task '<slug>'.` stub
   by the narrow-select regression. The original intent is unrecoverable from the row.
2. **Reference-only** — the task is defined solely by reference to a prior step's output
   that it does not carry (e.g. "fix the second collapsed task"). Executable only if the
   referenced list is reconstructed — which is the purpose of this document.
3. **Branch-lost** — the agent branch was deleted or never pushed; `integration_sweeper`
   exhausted recovery and closed the task to stop phantom `missing_branch` churn.
4. **Stale blocker** — the task is QUEUED behind a note describing a condition that no
   longer holds. These are the dangerous ones: they look actionable forever.

## The five collapsed tasks

Slugs are truncated in the DB at 88 chars; the tails below are the distinguishing part.

### 1. `…-recover-remaining--slice-1` — RESOLVED (mechanism 4: stale blocker)

* **Title / intent:** first slice of `-resolve-collapsed-`.
* **Acceptance:** branch merges into `orchestrator/dev` without regressing it.
* **Partial work:** branch `agent/backlog-batch-beethoven-a86bb21-recover-remaining--slice-1`,
  tip `6f82f95d`.
* **Blocking note:** `integrate REGRESSFAIL — merge would DELETE or STUB code that exists
  in orchestrator/dev; restore the named symbols before merging.`
* **Finding: the blocker is stale.** The branch tip is an ancestor of
  `origin/orchestrator/dev` (`git merge-base --is-ancestor` returns true) and
  `git diff merge-base..branch` is empty — the branch carries no net change and merging
  it is a no-op. The three files it originally introduced were removed from `dev` by
  hand and are absent from `dev`, from `master`, and from the working tree.
* **What actually went wrong.** Commit `6f82f95d` ("regen-from-cache(template)") added
  three files to the repo root:

  | path | content |
  |---|---|
  | `Step 5: Write a Minimal Test` | Python source, under a prose heading as its name |
  | `test_template_95fc17a.py` | the literal string `test_template_95fc17a.py` |
  | `unittest.main()` | empty |

  A coder's **prose reply was parsed as a file manifest**: the section heading, the
  code-fence's filename comment, and the snippet's last line each became a path. The
  generated test was broken anyway (`from patch_templates import lookup`, then a
  reference to a bare `patch_templates` that was never imported → `NameError`), and
  `test_template_95fc17a.py` would fail pytest *collection* at the repo root, since a
  lone bare word parses as a name reference.
* **Remedy shipped:** `repo_hygiene.find_response_artifacts()` +
  `runner/tests/test_response_artifact_guard.py` (13 tests). Detection only — these are
  tracked files by the time anyone notices, and this module never removes tracked
  content. The three real filenames are used verbatim as fixtures.
* **Validation:** 13,629 tracked files across `claude-orchestrator`, `apparently`,
  `smarter` and `tomorrow`; **0 false positives**. It found **3 previously-unknown live
  instances of the same defect**, listed under "Open findings" below.

### 2. `…-fix-second-collaps` — SUPERSEDED (mechanism 2: reference-only)

* **Acceptance:** "the second collapsed task is resolved."
* **Partial work:** none; no branch.
* Already dispositioned with `NO-ARTIFACT-JUSTIFIED: the task is defined only by
  reference to a prior step whose output it does not carry`. This register now supplies
  that output, so a re-queue is defensible — but see "Recommendation".

### 3. `…-fix-third-collapse` — QUARANTINED (mechanism 1: spec-lost)

* **Acceptance:** unrecoverable.
* **Partial work:** none.
* Note on the row: `spec-lost: the task prompt was overwritten with the "Complete the
  task '<slug>'." stub by the narrow-select regression`. Nothing in the row identifies
  which defect it was meant to fix. **Correctly quarantined; do not re-queue.** Any
  commit made against it would be invented rather than recovered.

### 4. `…-fix-fourth-collaps` — QUEUED, deduped (mechanism 2: reference-only)

* **Partial work:** none.
* Note: `dedup: waits on '…-recover-remaining-stale-tasks-identify-and-resol'
  (near-duplicate)`. Its blocker is `DECOMPOSED`, so the wait can never clear on its
  own — this is a stale blocker in the making.

### 5. `…-fix-fifth-collapse` — QUEUED (mechanism 2: reference-only)

* **Partial work:** none; note is `agentic-repair:rework` with no failure context.

Slices 2–5 of `…-recover-remaining--slice-N` are all QUEUED with no failure context
beyond `auto-sliced-before-agent` / `agentic-repair:rework`, and carry no branches. They
are reference-only in the same way.

## Open findings (not fixed here — tracked files, human decision)

The new guard surfaced three live instances of the mechanism behind collapse #1:

| repo | path |
|---|---|
| claude-orchestrator | `runner/utils/auto_branch_cleanup.py\nimport os\nENABLED = …` |
| claude-orchestrator | `runner/utils/backlog_batch.py\nimport os\nENABLED = …` |
| apparently | `hive-ops-dashboards/candidate-list.vue (assuming this is a Vue component)` |

The first two are whole Python source files captured **as the filename** — the intended
path, its body, and its newlines all became one path. The third is a model's
parenthetical aside appended to a real component path. All three are tracked, so
removing them is a content decision and is deliberately left to the operator.

## Recommendation

Of the five, only #1 had a recoverable subject, and it is now resolved. #3 should stay
quarantined. #2, #4 and #5 are reference-only shells with no branches, no failure
context and no acceptance criteria of their own; with #1 resolved and #3 unrecoverable,
there is nothing left for them to refer to. **Closing them as SUPERSEDED against this
register is more honest than leaving them QUEUED**, where they will keep being claimed,
re-sliced and repaired forever — which is the churn this stream was opened to stop.
