# Who owns `Missing_branch`? — call-flow trace

Task: `improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-fi`.
This step is explicitly **report only** — "update nothing yet". No behaviour is changed by
this commit. Traced against `origin/master@5c4eaf2f`.

**Answer up front: there is no single `Missing_branch` symbol.** The category is a
*string* (`"missing-branch"`), produced at two independent detection sites and consumed by
one shared remediation chokepoint. The authoritative owner of the *outcome* is
`runner/agentic_repair.py:repair_patch()`; the authoritative owner of the *classification*
is `runner/auto_remediate.py`.

## 1. Candidate files and functions found

Searching for `Missing_branch` / `missing_branch` / `missing-branch` / `recover-missing-branch`:

| file | symbol / line | role |
|---|---|---|
| `runner/auto_remediate.py` | `_MISSING_BRANCH` regex, **line 44** | **classifier** — decides a failure *is* this category |
| `runner/auto_remediate.py` | remediation loop, **lines 208–213** | routes the classified signal into repair |
| `runner/approval_merge.py` | **lines 444–453** | **second, independent detector** — an approved card whose branch is gone |
| `runner/agentic_repair.py` | `repair_patch()`, **line 365** | **handler** — the single chokepoint every path funnels through |
| `runner/agentic_repair.py` | `_TECHNICAL_CATEGORIES`, **line 76** | declares `missing-branch` a technical (evidence-bearing) category |
| `runner/agentic_repair.py` | `evidence_text()`, **line 206** | strips the `agentic-repair:missing-branch` marker so a prior repair is not read as evidence |
| `runner/branch_detection.py` | `detect_missing_branches()`, **line 79** | **scanner** — finds tasks whose branch is absent (fleet-wide sweep) |
| `runner/autopilot.py` | `RECOVERY_PREFIX`, **line 35** | counts `recover-missing-branch-*` tasks for the dashboard — reporting only |
| `runner/auto_decompose.py` | `_emit_decomposition()`, **~line 117** | pre-creates child branches so children never *start* missing |
| `runner/backlog_compactor.py` | **line 21** | treats the slug prefix as compactable backlog — reporting only |
| `runner/agentic_coders.py` | **line 753** | maps the slug prefix to the `recovery` stage — routing only |

## 2. The authoritative owner, by call flow

There are **two entry points**, and they converge:

### Path A — a task failure classified during remediation

```
runner/periodic.py  (loop)
  -> runner/auto_remediate.py : run()
       line 208   if rc == 0 and (... or _MISSING_BRANCH.search(signal)):
       line 209   category = "missing-branch" if _MISSING_BRANCH.search(signal) else ...
       line 210   upd = agentic_repair.repair_patch(t, signal, category=category, directive=...)
  -> runner/agentic_repair.py : repair_patch()          line 365
       line 378   is_operator_decision(task)      -> escalations answered first
       line 385   attempts >= GLOBAL_ATTEMPT_CEILING -> _terminal_patch()   (line 221)
       line 390   rc >= GLOBAL_REPAIR_CEILING        -> _terminal_patch()
       line 399   blind and rc >= BLIND_REPAIR_CEILING -> _terminal_patch()
       line 415   otherwise: {"note": "agentic-repair:missing-branch", ...} re-queued
  -> db.update("tasks", ...)                            auto_remediate line 204/211
```

### Path B — an approved merge card whose branch has vanished

```
runner/approval_merge.py : (approved-card sweep)
  line 444   if not _branch_exists(repo, branch) and not _fetch_and_check_branch(repo, branch):
  line 445   patch = agentic_repair.repair_patch(t, f"approved, but {branch} no longer exists",
                                                 category="missing-branch", directive=...)
  line 449   db.update("tasks", {"id": t["id"]}, patch)
  line 451   _notify("[merge] '<slug>' approved but branch <branch> is gone — re-queue to rebuild.")
```

Note Path B has already done the honest check — `_branch_exists` **and** a fetch — before
declaring the branch gone. Path A has not: it classifies from the *text of a signal*.

### The convergence

Both paths call `agentic_repair.repair_patch(..., category="missing-branch")`. Its own
docstring states the property that makes it authoritative:

> "This is the fleet's only chokepoint for repair, so the bound holds for every call site."

So:

- **Classification owner:** `runner/auto_remediate.py:44` (`_MISSING_BRANCH`) for Path A,
  `runner/approval_merge.py:444` for Path B.
- **Outcome owner (authoritative):** `runner/agentic_repair.py:repair_patch()` line 365.
  Every termination decision — ceiling, quarantine, re-queue — is made there and nowhere
  else.
- **Fleet-wide scanner (separate, no remediation):** `runner/branch_detection.py:79`
  `detect_missing_branches()`. It reports; it does not route.

## 3. Line references per hop

| hop | file:line | what happens |
|---|---|---|
| 1a | `auto_remediate.py:44` | `_MISSING_BRANCH = re.compile(r"branch.*missing\|no longer exists\|approved.*agent/", re.I)` |
| 1b | `auto_remediate.py:208` | signal matched against the regex |
| 2 | `auto_remediate.py:209` | category string chosen: `"missing-branch"` |
| 3 | `auto_remediate.py:210-212` | `repair_patch(..., category="missing-branch", directive=...)` |
| 4 | `agentic_repair.py:365` | `repair_patch()` — the chokepoint |
| 5 | `agentic_repair.py:378` | operator escalations answered before any ceiling |
| 6 | `agentic_repair.py:385-399` | ceilings -> `_terminal_patch()` (`agentic_repair.py:221`) |
| 7 | `agentic_repair.py:415` | otherwise re-queue with note `agentic-repair:missing-branch` |
| B1 | `approval_merge.py:444` | `_branch_exists()` + `_fetch_and_check_branch()` both false |
| B2 | `approval_merge.py:445-449` | same `repair_patch()` call, then `db.update` |
| S | `branch_detection.py:79` | `detect_missing_branches(repo_path, tasks)` — sweep, no remediation |

## 4. Two observations the follow-up step will need

1. **The Path A classifier is text-based and cannot see git.** `_MISSING_BRANCH` matches
   the *words* "branch ... missing" in a signal. It never checks whether the branch
   actually exists. Path B does check — and even fetches first. The asymmetry is the
   defect: a branch pushed to origin whose local ref was pruned (the fleet's *normal* end
   state per CLAUDE.md, "the agent/{slug} branch persists for merge-train pickup") reads
   as missing on Path A.
2. **The scanner had the same blind spot.** `branch_detection._list_agent_branches()` used
   `git branch --list`, i.e. LOCAL refs only.

Both are addressed on sibling branches
(`agent/improve-implement-automated-branch-management-impl-slice-5` for the scanner,
`agent/improve-missing-branch-auto-recovery-fleet-wide-slice-3-identify-owner-module-wi`
for the Path A classifier). This report is the map they were derived from.

## Acceptance

Per the task: no code changed. Verified on the unmodified tree —
`python -m py_compile runner/auto_remediate.py runner/agentic_repair.py
runner/approval_merge.py runner/branch_detection.py` exits 0, and
`python -m pytest runner/tests/test_missing_branch_owner_contract.py -q` passes.
