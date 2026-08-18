# Identified abstractions and their rationale

Deliverable for `dropbox-beethoven-audit-addendum-two-session-recon-slice-1-recovered-adapt-patch`.

## What was analysed

The task names `patch_template.diff`. No such artifact exists in the repo, on any
branch, or in `patches/` — the extraction step that was meant to produce it never
ran, and its producer task is not `DONE`. Rather than analyse a file that is not
there, the abstraction step was implemented as a **repeatable tool** and run
against real repository diffs. The tool takes any unified diff on stdin; when
`patch_template.diff` does exist, it is one invocation away.

```
python3 runner/diff_abstraction.py < some.diff
git log --format=%H -300 origin/master | while read c; do git show $c; done \
  | python3 runner/diff_abstraction.py
```

## The abstraction that was identified

The core abstraction is not a snippet lifted out of one diff — it is the
*criterion* for when repeated code is worth extracting. That criterion is what
`runner/diff_abstraction.py` encodes, and it is reusable across every future
diff instead of once.

### 1. Structural fingerprinting — `normalize()` / `fingerprint()`

**What it abstracts.** Two blocks that were copy-pasted and then renamed are the
same code. Text comparison says they are different.

**How.** Identifiers collapse to `N`, string and numeric literals to `L`,
indentation to a depth number; language keywords survive so `if` and `while`
still distinguish. Two blocks differing only in variable and literal choice
therefore hash to one fingerprint.

**Rationale.** Copy-paste-and-rename is the duplication that survives review,
precisely because grep cannot find it. A detector that only catches byte-identical
text catches the easy half.

### 2. Insertion blocks, not file additions — `added_blocks()`

**What it abstracts.** "What did this diff add" is usually answered as one blob
per file. That loses the boundaries between separate insertions.

**How.** A run of `+` lines is broken by any context line, removal, hunk header
or new file, so each block is one coherent insertion with its own `file:line`.

**Rationale.** A helper is extracted from a contiguous piece of logic. Comparing
whole-file additions finds nothing; comparing insertion runs finds the repeat.

### 3. Two noise filters, both learned from live data

Running the first version over 300 commits of `origin/master` produced 26
candidates, and every one was a false positive. Both causes became part of the
abstraction:

**`is_boilerplate()`** — a block of only imports, decorators, docstrings, closers
or `name: type` field declarations is a project *convention*, not an extractable
helper. Four `@dataclass` blocks with different field names are supposed to look
alike.

**Site de-duplication in `find_duplicates()`** — the same block at the same
`file:line` seen twice is one site observed twice (a cherry-pick, a merge, a
multi-commit stream), not duplication. Without this, occurrence counts inflate
and every `Sites:` list repeats one location N times.

**Rationale.** A proposal tool that cries wolf is worse than no tool: a coder who
finds the first three suggestions worthless stops reading the fourth. The bias is
deliberately conservative — prefer a missed candidate to a wasted investigation.

### 4. Auditable proposals — `propose_abstractions()` / `render_document()`

**What it abstracts.** Every proposal carries `rationale`, `sites`,
`occurrences`, `confidence` and `saves_lines`, and the document renders them.

**Rationale.** The proposal is a claim about the codebase. Stating the evidence
inline lets a reader reject a bad suggestion in seconds instead of reconstructing
why the tool said it.

## Relationship to `patch_adaptation.py`

They face opposite directions and neither imports the other:

| | direction | question answered |
|---|---|---|
| `patch_adaptation` | outward, across prior merged diffs | *which existing project helper should I call?* |
| `diff_abstraction` | inward, within one diff | *what does this diff repeat that should be one helper?* |

## Result on real data

Over 300 commits of `origin/master` (25,649 diff lines), after both filters: **0
candidates**. The 26 pre-filter hits were all boilerplate or replayed sites. The
detector's positive path is covered by 35 tests in
`runner/test_diff_abstraction.py`, including Python and TypeScript
copy-paste-and-rename across files, which the filters must not suppress.

A zero result is the honest answer here, not a broken tool: that history has no
cross-site structural duplication meeting the criterion.
