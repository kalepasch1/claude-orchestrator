# Patch-template abstractions: what we lift from a prior diff, and why

Owner module: `runner/patch_adaptation.py`
Consumer: `runner/patch_templates.py` → `build()` → `patch_adaptation.directive()`
Tests: `runner/tests/test_patch_adaptation_snippets.py`

## The problem this addresses

`patch_templates.build()` injects the nearest merged diffs into a queued task's
prompt so the agentic coder adapts proven work instead of drafting net-new code.
Until now that injection carried only **names**: "a prior diff defined
`normalize_slug`", "a prior diff called `select()`".

A name is enough to tell a coder *that* an abstraction exists. It is not enough
to tell it *what shape* the abstraction had. Handed a name alone, the coder
reconstructs the function from the task description — which is precisely the
net-new drafting the reuse-first policy is meant to prevent. The prior diff's
structure is discarded at exactly the moment it would have been useful.

## The abstractions

Analysis of the extracted `patch_template.diff` payloads identified four classes
of reusable content. Three were already captured; the fourth — the concrete code
change itself — was not, and is what this work adds.

### 1. `changed_files(diff_text)` — the topology abstraction
**Already present.** Answers *where* a change lives. Prefers the `diff --git`
headers and falls back to `+++` lines, so it degrades gracefully on diffs that
have been truncated by the merged-diff library.

**Rationale:** owner directories are the single strongest signal against the
most common agent failure mode — creating a parallel module beside the real one.

### 2. `extract_patterns(diff_text, files)` — the vocabulary abstraction
**Already present.** Answers *what names* a change introduced (`defines`), *what
existing helpers it leaned on* (`reuses`), *what it imported*, *where its tests
went*, and *what naming convention* the area follows.

**Rationale:** `reuses` is deliberately filtered against `_NOISE` and private
`_`-prefixed names. A helper that a *merged* patch called is a helper that
exists and is public — a safe instruction to give a coder. A private helper is
not, because it may be module-local to a file the new task will never touch.

### 3. `merge_patterns(pattern_list)` — the consensus abstraction
**Already present, extended here.** Unions several per-diff profiles into one.
Where two prior diffs disagree the union wins; where they agree the signal is
implicitly stronger because it survives in every profile.

**Rationale:** a single nearest-neighbour diff is a weak sample. Two or three
agreeing on an owner directory is close to a fact about the repo.

### 4. `reusable_snippets(diff_text)` — the code-shape abstraction (new)
Lifts the added body of every top-level definition out of the diff and returns
it as `{"name", "kind", "language", "signature", "body"}`.

**Rationale:** this is the abstraction the previous three were approximating.
Names describe the change; the snippet *is* the change. Rendering it back into
the patch template lets the coder edit proven code rather than reproduce it.

Four constraints keep the abstraction safe to inject:

| Constraint | Mechanism | Why |
| --- | --- | --- |
| Only added code is lifted | any non-`+` line clears the collector | Context lines already exist in the target repo. Emitting them would imply the prior patch made edits it never made. |
| Hunk and file headers end a body | `@@`, `diff --git`, `+++`, `---`, `index ` clear the collector | Two hunks are two disjoint regions; splicing them produces code that never existed. |
| Bodies are dedented | `_dedent_body()` strips the shared leading indent | A method body pasted at its original indent reads as broken code and invites the coder to "fix" the indentation of unrelated lines. |
| Volume is bounded | `MAX_SNIPPETS = 4`, `SNIPPET_BODY_LINES = 12` | Snippets carry whole bodies and cost far more prompt budget than names. The coder needs the shape, not a verbatim replay it can fetch in full from the merged-diff library. |

### 5. `_render_snippets(snippets)` — the presentation abstraction (new)
Prefixes every emitted line so the block stays diff-shaped, and labels each
snippet with why it is present.

**Rationale:** `preliminary_diff()` is explicitly *not an appliable patch* — it
is the shape a patch should take. A block that stops looking like a diff halfway
through invites an agent to try to `git apply` it. The rendering contract is
pinned by `test_every_rendered_line_stays_diff_shaped`.

## Design decisions worth recording

**Additive, not replacing.** `snippets` is a new key alongside `defines`; no
existing key changed meaning. Every caller of `extract_patterns` and
`merge_patterns` keeps working unmodified. This is what "smallest mergeable
diff" means for a module with several live consumers.

**Fail-soft throughout.** `reusable_snippets` returns `[]` on `None`, integers,
dicts, and text that is not a diff. `patch_templates.build()` already wraps its
adaptation call in a bare `except`, but a template builder that can be broken by
one malformed archived diff would silently degrade every task in the queue —
so the failure is contained at the source rather than at the call site.

**Regex table over branching.** `_SNIPPET_HEADERS` is an ordered tuple of
`(pattern, kind, language)`. Adding a language is one row, not a new branch in
a growing `if` chain. Order matters: `class` precedes `def` so a decorated
method is attributed to its own definition line.

**Named constants over literals.** `MAX_SNIPPETS` and `SNIPPET_BODY_LINES` are
module-level and referenced by the tests, so a future budget change is one edit
and the tests move with it rather than against it.

## Verification

- `runner/tests/test_patch_adaptation_snippets.py` — 21 tests, all passing.
- Coverage: extraction (python + typescript), context/removed-line exclusion,
  hunk-boundary termination, dedent, bounding by both default and explicit
  limit, garbage input, profile integration, dedupe across diffs, rendering
  shape, truncation, and the two `directive()` paths.
- Pre-existing unrelated failures in
  `runner/tests/test_patch_template_conflict_handling.py` (12) were confirmed
  present on unmodified `origin/master` before this change and are untouched
  by it.
