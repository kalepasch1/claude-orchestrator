# Patch-template abstractions — what to reuse, and why

Task: `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-adapt-patch-template`.

> "Analyze the extracted `patch_template.diff`. Identify core code changes … and abstract them into
> reusable snippets or functions. Document these abstractions with comments explaining their
> purpose. **Acceptance: Create a document outlining the identified abstractions and their
> rationale.**"

The acceptance criterion is a document, so this document is the deliverable. Verified against
`origin/master` @ `59de85f2`.

## Correction: there is no `patch_template.diff`

`find . ~/.claude-orchestrator -name "patch_template*.diff"` returns nothing; no such file is
tracked, and none exists in the runtime store. What *does* exist is the machinery the phrase
points at:

| Path | Role |
|---|---|
| `runner/patch_templates.py` | build / store / **lookup** a template; the `pre_claim_hook` that injects one into a task prompt |
| `runner/patch_template_apply.py` | apply a template to a repo |
| `runner/patch_transplant.py` | adapt a *proven prior diff* into a new context |
| `runner/merged_diff_library.py` | find those proven prior diffs |
| `runner/tests/PATCH_TEMPLATE_REGISTRY.md` | hash → owner module → acceptance test |

So the analysis below is of the **template mechanism as it actually exists**, not of a diff file
that does not. Abstracting from a file I cannot read would be fabrication.

---

## The five abstractions worth reusing

### A1 — `lookup(template_id)`: resolve-by-id with a two-tier fail-soft store

```python
def lookup(template_id):
    """Resolve a stored patch template by id. Fail-soft: returns {} on any miss/error."""
```

**Shape:** normalise the key → try the **local JSONL** store (`.runtime/patch_templates.jsonl`,
newest matching line wins) → fall back to the **`knowledge` table** → return `{}`.

**Why it is the right abstraction.** It separates *identity* from *storage*. Callers hold a
12-hex id and never learn whether the answer came from disk or the DB, so the DB can be down and
recovery still works. Corrupt JSONL lines are skipped individually rather than failing the read.

**Reuse it for:** any content-addressed artifact the fleet stores and later needs back — templates,
diffs, receipts, proofs. Do not re-derive the local-first ordering; it is what makes the store
useful during an outage, which is exactly when recovery runs.

### A2 — `exact_slug_re(slug)`: boundary-exact identifier matching

```python
return re.compile(r"(?<![A-Za-z0-9._-])" + re.escape(slug) + r"(?![A-Za-z0-9._-])")
```

Lives in `landed_evidence.py`, and is the single most load-bearing four lines in the fleet.

**Why.** A truncated or unanchored slug match caused a **76.6% phantom rate** across 13,816
"MERGED" tasks. Three failure modes, all fixed by this one pattern plus a tree check:
scaffolding that names the slug it failed to recover; 48-char prefix collisions letting sibling
slices certify each other; and empty commits counting as evidence.

**Reuse it for:** every "did X land / is X referenced" question. `re.escape` also means a slug is
never accidentally read as a regex.

### A3 — The fail-soft boolean contract: *return the outcome, not the completion*

Codified in `tests/test_merged_diff_memory_capture_bool.py`:

> "return True if the memory file was written successfully, False on ANY error (bad git refs, no
> diffs, write failure), and never raise. … The load-bearing case is `no diffs -> False`.
> Returning True there would tell a caller that memory is current when nothing was persisted."

**Why.** The recurring defect in this codebase is *a guard that reports success because the
function completed rather than because the work happened*. A function that returns `True` after
doing nothing is worse than one that raises, because nothing downstream can tell.

**The reusable rule, in three lines:**

```python
try:
    return _do_the_work(...)          # True only if the work HAPPENED
except Exception as e:
    logger.warning("<module>: <op> failed: %s: %s; fail-soft False", type(e).__name__, e)
    return False                       # logged, then swallowed — never a silent pass
```

A broad `except` is the convention here; a **silent** one is the defect.

### A4 — Direction of failure is a per-call-site decision

`branch_lease.acquire` fails **CLOSED**:

> "An unavailable lease control plane is not proof of contention. Fail closed and let the runner
> requeue instead of turning an RPC outage into a task error."

`branch_lease.heartbeat` fails **SOFT (ALIVE)** on the same outage.

**Why both are right.** Acquire guards a *safety* property (one writer per branch) — ambiguity must
block. Heartbeat guards a *liveness* property — ambiguity must not kill healthy work. A single
"fail-soft everywhere" policy gets one of them wrong.

**Reuse:** state the direction and the reason in a comment at every fail-soft branch. This is a
documentation abstraction, not a code one, and it is the one most often skipped.

### A5 — Additive, non-mutating hooks

`pre_claim_hook` returns `{**task, "prompt": new_prompt}` and carries this comment:

```python
# DO NOT write back to DB — keep original prompt intact for retries
```

The header records why: `"FIXED 2026-07-11: removed db.update() that permanently corrupted prompts."`

**Why.** A hook that mutates shared state makes retries non-idempotent — the second attempt sees a
prompt the first one rewrote. Returning a new dict keeps every retry identical to the first.
The `MARK` sentinel makes it idempotent in the other direction too: an already-templated task is
returned unchanged rather than double-templated.

**Reuse:** any enrichment hook in the pipeline. Take a value, return a new value, touch nothing.

---

## The pattern behind all five

Every one of these came from a **measured incident**, and each is written so the incident cannot
recur silently:

| Abstraction | The failure it encodes |
|---|---|
| A1 `lookup` | recovery could not resolve a template back from its id |
| A2 boundary match | 10,584 phantom merges (76.6%) |
| A3 outcome-not-completion | "success" reported for work that never happened |
| A4 fail direction | an RPC outage becoming either a task error or a double writer |
| A5 additive hooks | a hook permanently corrupting task prompts |

**The meta-rule for future slices:** when you find yourself writing one of these five shapes, import
it instead. When you must write a new one, record the incident that justifies it in the docstring —
that is what makes the next agent reuse it rather than rediscover it.

## Where the registry fits

`runner/tests/PATCH_TEMPLATE_REGISTRY.md` maps each template hash to its owner module and
acceptance test, and requires the row to be added **in the same commit** as a new hash-scoped test.
That convention is itself abstraction A1 applied to tests: an artifact you can resolve back from
its id. A template with no registry row is a template nobody can find again.

*Analysis only; no source modified.*
