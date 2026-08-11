# Owner module for the wave-c slice-2 patch template

Deliverable for `dropbox-wave-c-compounding-codegen-platform-spine--slice-2-find-owner-module`.
**No code was modified**, per the task instruction.

## The patch template's intent

The slice-2 template is a MERGED-DIFF LIBRARY directive:

> *adapt proven prior diffs before drafting net-new code* —
> `SOURCE illuminati/…-review-gate-wave-timeline… similarity=0.429`,
> `SOURCE smarter/cont-1042d0 similarity=0.413`, then
> *REUSE FIRST: a solved implementation exists — adapt it instead of rebuilding.*

So the owner is whatever decides **which prior work a coder is shown, and how it
reaches the prompt**. That is not one function; it is a four-module chain with a
single call site.

## The call site — where integration actually happens

**`runner/runner.py`, lines ~3716–3731**, inside the claim loop, immediately after
a task is claimed and before the agent runs. The hooks execute in this fixed order:

```python
t = reuse_first.pre_claim_hook(t)        # ~3719
t = patch_transplant.pre_claim_hook(t)   # ~3724
t = patch_templates.pre_claim_hook(t)    # ~3729
```

Each call is individually wrapped in `try/except` logging to `_log.debug`, so a
failing hook degrades the prompt rather than dropping the task. **Any new
prompt-shaping stage belongs here, in this ordering, with the same guard.**

## The four modules

### 1. `runner/merged_diff_library.py` — the evidence layer

The source of "which prior diffs resemble this task". Nothing else queries the
`merged_diffs` table.

| Function | Purpose |
|---|---|
| `find(task, limit=3)` | Jaccard word-overlap against stored merged diffs; returns hits with `similarity`, `project`, `slug`, `summary`, `diff`. Filters below `0.12`. |
| `directive(task)` | Renders the `MERGED-DIFF LIBRARY: …` / `SOURCE …` block seen at the top of the slice-2 template. |
| `adapter_directive(task)` / `intent_graph(task)` | The same, expressed as adapter shapes plus an `intent_signature`. |
| `record(project, slug, kind, prompt, repo, base, head)` | Writes a merged diff back into the library. Called from `runner.py:2248`. |
| `features` / `intent_signature` / `adapter_template` | Feature extraction the above build on. |

**Reads from:** `merged_diffs` table via `db.select`, falling back to `knowledge`.
**Fail-soft:** every path returns `[]` / `""` on DB or parse failure.

### 2. `runner/reuse_first.py` — the decision layer

Decides whether a solved implementation exists at all.

| Function | Purpose |
|---|---|
| `find_reusable(task)` | Best Jaccard match across capability/knowledge rows; returns a hit only at `similarity >= KEYWORD_THRESHOLD` (`0.35`). Skips `status == "retired"` capabilities. |
| `rewrite_prompt(task, hit)` | Prepends `merged_diff_library.directive(task)`, then the `REUSE FIRST: …` / `SOURCE:` / `SUMMARY:` block, then the original prompt. |
| `pre_claim_hook(task)` | The stage. Idempotent on `NOTE_MARK` (`"[reuse-first: matched"`). **Persists the rewrite with `db.update("tasks", …)`** and emits a best-effort `notifications` digest row. |

### 3. `runner/patch_templates.py` — the scaffold layer

Turns intent plus nearest merged diffs into the `PATCH TEMPLATE <id>` body.

| Function | Purpose |
|---|---|
| `build(task)` | Returns `(template_id, body)`. `template_id = sha1(slug + intent)[:12]`. Body = header, `Intent:`, `Acceptance:`, `Implementation slots:` 1–3, `Prior merged patterns to adapt:`. |
| `pre_claim_hook(task)` | The stage. Idempotent on `MARK` (`"[patch-template:"`). Calls `_ensure_branch` (branch recovery via `patch_recovery`), then `_store`. |
| `lookup(template_id)` | Resolves a stored template: local `.runtime/patch_templates.jsonl` first, then the `knowledge` table. |
| `inject_prompt(task)` | Same injection without the branch-recovery or storage side effects. |

**Critical constraint — do not regress:** `pre_claim_hook` **must not** write the
prompt back to the DB. The `db.update()` that used to live here permanently
corrupted prompts and was removed 2026-07-11; the comment marking the fix is on
the function. A requeued task is re-hooked on every claim, so a write-back
accumulates one template per attempt.

### 4. `runner/patch_transplant.py` — the middle stage

Sits between the other two in the chain and also imports `merged_diff_library`.
Consult it before inserting anything at position 2.

## Invariants a new integration must preserve

1. **Order is load-bearing.** `reuse_first` prepends first; `patch_templates`
   prepends its template *above* that. The final prompt reads: patch template →
   marker → reuse-first block → original request.
2. **Each stage guards on its own marker.** `NOTE_MARK` and `MARK` respectively.
   Skipping the guard double-injects on every reclaim.
3. **Only `reuse_first` persists.** `patch_templates` returns a modified dict and
   leaves `tasks.prompt` alone.
4. **Every stage is fail-soft** and individually wrapped at the call site.

Regression coverage for the composition itself:
`runner/tests/test_reuse_first_patch_template_chain.py`.

## Where a slice-2 change should go

| Change | Owner |
|---|---|
| which prior diffs are found, or how similarity is scored | `merged_diff_library.find` |
| whether a task is treated as "already solved" | `reuse_first.find_reusable` (`KEYWORD_THRESHOLD`) |
| wording/structure of the `REUSE FIRST` block | `reuse_first.rewrite_prompt` |
| wording/structure/slots of the patch template | `patch_templates.build` |
| adding a new prompt-shaping stage | `runner/runner.py` ~3716–3731, same `try/except` shape |

Do **not** create a parallel prompt-rewriting module. Four already prepend to the
same field; a fifth outside this chain would inject without a marker guard and
duplicate on every reclaim.
