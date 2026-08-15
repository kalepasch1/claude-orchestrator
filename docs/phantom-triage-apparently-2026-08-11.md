# PHANTOM_UNVERIFIED triage — apparently, 2026-08-11

Register item R3. *"No new autonomous workstream should be pointed at this pipeline until it is
triaged."*

## Counts

Measured against `/Users/kpasch/Documents/apparently` (2,371 refs, 1.6 MB of commit messages
indexed) using `landed_evidence.find_evidence` as the predicate.

| class | count | share |
|---|---:|---:|
| **(a) landed — promotable** | **3** | 0.2% |
| **(b) no trace — safely closable** | **1,553** | 95.2% |
| **(c) ambiguous — needs a human** | **75** | 4.6% |
| total PHANTOM_UNVERIFIED | 1,631 | |

The register said 2,017; the live count when this ran was 1,631, so 386 had already moved by other
means. A 150-row pilot run returned 0 / 143 / 7 — the same 95.2% / 4.6% split, which is why the
full-run numbers are believable rather than an artifact of one pass.

**95% of this backlog never produced a single line of code.** That is the headline. It is
consistent with the 2026-08-04 forensic finding that these rows were manufactured by bulk UPDATEs,
a "bulk-resolved: no branch, nothing to deploy" sweep, and a self-certifying recovery-stub loop —
not by work that got lost.

## What each class means

**(a) landed — 3 rows.** `find_evidence` returned a commit that names the slug at a token
boundary, is not recovery scaffolding, and actually changes the tree:

```
hive-filing-ready-gate-slice-3       1a3309887719  origin/orchestrator/dev
hive-kg-modeled-after-seed-slice-4   1698079ddc3e  origin/orchestrator/dev
weekly-lint-apparently               2737d0b83635  origin/orchestrator/dev
```

**Not promoted by this run.** Promotion requires `artifact_commit` to be persisted first — the
`evidence_gate_before_update` trigger enforces exactly that, and `phantom_reclassify.py`'s own
closing comment specifies the same order. The three shas above are the input to
`phantom_recovery.py`, which is the tool that owns promotion. "No task promoted without landed
evidence" therefore holds by construction: this script cannot promote anything at all.

**(b) no trace — 1,553 rows.** No `agent/<slug>` ref anywhere in the repo, and no commit anywhere
names the slug. There is nothing to recover. Closed as `CLOSED` with a note recording the reason.
Only `state` and `note` are touched, so the closure is fully reversible.

**(c) ambiguous — 75 rows.** Two shapes, both listed with the missing evidence named:

- *branch exists, no landed evidence* — e.g.
  `hive-support-entity-relationship-source-verify-entity-relationship-tests`. A branch was created;
  nothing on it delivers the slug. Missing evidence: whether the branch has real content or is an
  empty checkout.
- *named in a commit, but no commit changes the tree* — e.g. `cade-anachronism-sentinel`,
  `qafix-apparently-07171746`, `hedge-funded-prepositioning-slice-4`. This is the scaffolding /
  empty-commit shape `SCAFFOLD_RE` exists to refuse. Missing evidence: whether a real commit was
  GC'd, or whether only the stub ever existed.

**Never auto-closed.** These are the rows where a wrong answer costs real work.

## Prior art — surveyed before writing anything

| Module | What it does | Decision |
|---|---|---|
| `runner/landed_evidence.py` | The sound "did this land?" predicate. Boundary-exact slug match, rejects recovery scaffolding, requires a tree change. | **Called, not reimplemented.** Its header documents three earlier grep-based attempts that were unsound in three separate ways; a fourth would have been the fourth mistake. |
| `runner/phantom_recovery.py` | Reconciles phantom rows that already carry an `artifact_commit`, via `merge_truth`. | **Left alone, and fed.** It is the right tool for the 12 apparently rows that have an `artifact_commit`, and the wrong tool for the other 1,619 — it starts from a column that is empty. This triage is the step *before* it. |
| `runner/phantom_reclassify.py` | Created this backlog. | **Its instruction implemented.** Its closing comment: *"find real evidence (landed_evidence.find_evidence), set artifact_commit to it, and only then set MERGED."* |
| `runner/quarantine_triage.py`, `stash_triage.py`, `blocked_triage.py` | Sibling triages for other states. | Naming and dry-run-by-default conventions followed. |

New file: `runner/phantom_triage.py`. It adds the one thing none of the above does — classify by
**git evidence** rather than by a database column.

## Design notes

- **Dry run by default.** `--apply` closes class (b) only, and re-checks each row is still
  `PHANTOM_UNVERIFIED` at write time, so it cannot clobber a row that progressed since the scan.
- **Cheap pre-filter, sound authority.** One pass builds an index of every commit subject+body;
  `find_evidence` is only invoked for slugs that appear in it. The index is a filter, never the
  answer — invoking the sound predicate 1,631 times would otherwise take hours.
- **`CLOSED`, not a new state.** `task_state` is a Postgres enum; a bespoke `CLOSED_NO_EVIDENCE`
  label would need a migration. The reason lives in the note.

### A bug worth recording

The first `--apply` run failed with a bare `HTTP 400` on every row. Cause: `db.update()` builds the
PostgREST operator itself (`f"eq.{v}"`), unlike `db.select()` which takes params verbatim. Passing
`{"id": "eq.<uuid>"}` produced `id=eq.eq.<uuid>`. The asymmetry between the two functions is a
genuine footgun; the fix is commented in place so the next caller does not repeat it.

## Coverage — what this triage did not reach

- **Rows whose repo is not cloned locally.** Only `apparently` was triaged. beethoven's 4,824
  phantom rows are untouched; the same script handles them with `--project beethoven`.
- **Evidence in another repo.** A task whose code landed in a sibling repo reads as no-trace here.
- **Correctness.** A landed commit proves code shipped, not that it works.
- **The 69 QUARANTINED rows** are out of scope for this run; `quarantine_triage.py` owns them.
- **The 75 ambiguous rows** are classified, not resolved. Resolving them needs a human to look at
  each branch — that is the point of the class.
