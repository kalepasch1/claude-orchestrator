# ChatGPT/Codex local build-evidence reconciliation — beethoven

Audit fingerprint: `169a0a07fa18ff3b9a70ea6de20b366987e91ef798d95a7a32868189dcd66a55`

Base: `origin/master` @ `bcacf428e` · ledger: `.orch/recovery-ledger-169a0a07fa18.json`

The committed ledger is the output of:

```bash
python3 tools/reconcile_rescue_refs.py \
  --base origin/master \
  --fingerprint 169a0a07fa18ff3b9a70ea6de20b366987e91ef798d95a7a32868189dcd66a55 \
  --out .orch/recovery-ledger-169a0a07fa18.json
```

Regenerate with `--newest master` added. That flag did not exist when this scan ran;
it was added by this task *because* of what the scan got wrong, and it applies the
59 corrections below automatically:

```bash
python3 tools/reconcile_rescue_refs.py \
  --base origin/master --newest master \
  --fingerprint 169a0a07fa18ff3b9a70ea6de20b366987e91ef798d95a7a32868189dcd66a55 \
  --out .orch/recovery-ledger-169a0a07fa18.json
```

The ledger is committed as the tool produced it, so the first command still
reproduces it byte for byte and the correction stays visible rather than being
quietly folded in.

## Result

**771 evidence items classified, 0 UNKNOWN.** The task prompt sampled 595 refs; the
live namespace held 771 at reconciliation time, and classification is recomputed
from live refs rather than from the snapshot. Every `refs/orch-rescue/*` ref was
treated as read-only — nothing was deleted, reset, cleaned, popped or moved.

| Classification | Tool | After review | Δ |
|---|---:|---:|---:|
| SUPERSEDED_BY_NEWER | 214 | 273 | +59 |
| ALREADY_PRESENT | 197 | 197 | |
| CONFLICTED_NEEDS_FOCUSED_TASK | 197 | 197 | |
| RECOVERABLE_VALUE | 151 | 91 | −60 |
| ACTIVE_IN_ANOTHER_TASK | 12 | 13 | +1 |

Nothing was applied in this pass. Per the coordination rule, items with remaining
value keep durable provenance and get focused follow-ups; conflicts are never
force-overwritten.

## The 60 corrections, and why a mechanical verdict was not enough

`reconcile_rescue_refs.py` answers "does this diff still apply to the base?" That is
the right question and it is not the whole question. Two ways it went wrong here,
both worth fixing in the tool rather than re-deriving next time.

### 59 refs would have resurrected a deliberate deletion

Thirty-nine percent of the RECOVERABLE_VALUE set — 59 of 151 — touch only these two
paths:

    web/types/log.js
    web/utils/cookie-compat.js

They apply cleanly to `origin/master` because they are still *on* `origin/master`.
They are not on the newest lineage. `d63e93da1` (2026-09-09) —

    finish fbd49cff8: drop the last 2 compiled .js files shadowing their .ts sources

— removed them one day before this reconciliation, completing `fbd49cff8`
(2026-07-10), which had removed the other ten. That commit is on local `master` and
on `orchestrator/dev`; it has not reached `origin/master` yet.

So the base this scan was pointed at is behind the decision. Applying these 59 refs
would re-add two compiled `.js` files that shadow their TypeScript sources — undoing
a day-old cleanup, and reintroducing exactly the shadowing bug `fbd49cff8` was
written to fix. **Reclassified SUPERSEDED_BY_NEWER.**

The general shape: *the newest implementation wins* cannot be evaluated against a
base that does not contain the newest implementation. `--base origin/master` is
stale whenever the merge train is holding unpushed commits, which is most of the
time.

**Fixed in the tool, not just in this report.** `reconcile_rescue_refs.py` now takes
`--newest <ref>` and, before calling anything RECOVERABLE_VALUE, refuses any ref
whose every touched path is present in the base but gone from the newer lineage —
recording the deleting commit as the evidence. The rule is `deletion_supersedes`,
pure and predicate-injected; `tools/tests/test_reconcile_rescue_refs_deletion_supersedes.py`
covers it against real repositories. It is opt-in, so a caller that does not pass
`--newest` gets exactly the behaviour it had before.

Two edges the tests pin, because both would be tempting to get wrong:

- The check is `all`, not `any`. A ref touching one deleted file and one live file
  keeps its remaining value — dropping it to avoid resurrecting the first would
  discard the second. Partial recovery is a focused follow-up, not a verdict this
  rule may reach alone.
- A path absent from the base *and* the newer lineage is not a deletion. It is a
  file neither branch ever had, which is precisely what a recovery candidate looks
  like.

### 1 ref is already carried by a sibling task

One item's files are the five recovered test files now on
`agent/chatgpt-local-reconcile-beethoven-4a838e298f31` @ `9a4e0786`, pushed earlier
in this same executor run under fingerprint `4a838e298f31`. Recovering them again
would duplicate that branch. **Reclassified ACTIVE_IN_ANOTHER_TASK.**

## The 91 that do have remaining value

Grouped by what they touch, so a follow-up can be scoped per cluster rather than per
ref. None of these paths exist on `origin/master` or on the newest lineage.

| Cluster | Refs | Distinct files | Newest ref |
|---|---:|---:|---|
| unclustered singletons | 43 | 49 | 2026-09-10 |
| autoclear policy engine | 27 | 21 | 2026-09-08 |
| recovery / reconcile tooling | 13 | 12 | 2026-09-10 |
| counterfactual replay + `src/orchestrator` package | 3 | 11 | 2026-09-07 |
| `cowork-skills/*.SKILL.md` set | 2 | 18 | 2026-09-10 |
| hisanta contracts | 2 | 5 | 2026-09-05 |
| `CLAUDE.md` only | 1 | 1 | 2026-09-06 |

Three notes for whoever picks these up.

**The autoclear cluster is the substantial one.** 27 refs converging on
`runner/autoclear.py`, `runner/autoclear_policy.py` and `runner/autoclear_rules.yaml`,
with `runner/realtime_monitor.py` and `runner/scoreboard.py` alongside. Twenty-seven
snapshots of one feature is a feature that was being worked on and never landed, not
twenty-seven separate recoveries. It wants one focused task that takes the newest
snapshot and ignores the rest.

**The hisanta cluster is in the wrong repo.** `hisanta/contracts/family.py` and
`hisanta/hisanta/contracts/family.py` — note the doubled directory — are
santas-secret-workshop paths captured by a sweep that ran with the wrong working
directory. Recovering them into beethoven would be wrong twice over. They belong to
the `santas-secret-workshop` project or nowhere.

**The `cowork-skills/` set is this executor's own skill files.** Eighteen
`cowork-executor-N.SKILL.md` files plus a README. Whether beethoven should carry a
copy of the fleet's skill definitions is an operator question, not a recovery
question.

## Method

Classification vocabulary and the apply verdict come from
`tools/reconcile_rescue_refs.py` and `tools/recovery_apply_check.py` — one definition
of "still applies", shared by every reconciler, so two of them cannot disagree. The
corrections above were made by checking each RECOVERABLE_VALUE path against the
newest lineage (local `master`) as well as the scan base, and by checking the
recovered file sets against branches this run had already pushed.

Full per-item provenance — ref, sha, subject, created_at, touched files, evidence and
disposition for all 771 items — is in `.orch/recovery-ledger-169a0a07fa18.json`.
