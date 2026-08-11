# Patch template structure — observations

Structural analysis of the patch template emitted by `patch_templates.build()`
(source template observed: `smarter/cont-1042d0`). **Analysis only** — nothing here
adapts or reuses template content; every entry describes shape.

Generated and re-checkable via `runner/patch_template_structure.py`:

```
python3 runner/patch_template_structure.py < some-template.txt
```

## Reference body

```
PATCH TEMPLATE 2e0c728e44a0
Intent: compactor continuation reuse session smarter windows
Acceptance: preserve existing behavior, make the smallest mergeable diff, run build/tests.
Implementation slots:
1. Locate the existing owner module/function before adding new files.
2. Reuse matching project helpers and naming conventions.
3. Add or update the narrowest test/check that proves the requested behavior.
Prior merged patterns to adapt: none found; keep the patch template reusable.
[patch-template:2e0c728e44a0]
```

## Observations

**Prefix**

- Line 1 is always `PATCH TEMPLATE <id>`, where `<id>` is a lowercase hex digest,
  12 characters in practice (`sha1(slug + intent)[:12]`).
- No blank line separates the header from the first label.

**Suffix**

- The body ends with the marker `[patch-template:<id>]`, produced by
  `MARK = "[patch-template:"` in `patch_templates.py`.
- The marker id must equal the header id. Drift between the two is a defect:
  `inject_prompt` and `pre_claim_hook` grep for `MARK` to decide idempotency, while
  `lookup()` resolves by the header id — disagreement makes a template unlookupable.
- The marker is a *separator*, not a terminator: the original task prompt is appended
  after it, so anything parsing the template must stop at the marker.

**Labels vs. sections**

- `Key: value` on one line is a *label*. Observed labels, in order:
  `Intent:`, `Acceptance:`, `Prior merged patterns to adapt:`.
- `Key:` with nothing after the colon is a *section header* introducing a list.
  Observed section: `Implementation slots:`.
- Label keys are Title-case, single-colon, never indented.

**Slot list**

- Slots are numbered `N. ` (digit, period, single space), sequential from 1.
- Three slots in the default body; each is one imperative sentence ending in a period.
- Slot text is advice about *where* to put code, never code itself.

**Prior-patterns section**

- Two shapes, chosen by whether `merged_diff_library.find()` returned hits:
  - hits → the label line `Prior merged patterns to adapt:` followed by `- ` bullets
    of the form `- <project>/<slug> sim=<float>: <summary>`;
  - no hits → a single label line with the inline value
    `none found; keep the patch template reusable.`
- Bullets use `- ` (hyphen, space). Similarity is annotated `sim=` with a bare float.
- The `<project>/<slug>` pair is the stable reference format for prior work.

**Comment style**

- The default body contains no comments. When a template carries them they are `#`
  (hash) style, matching the Python side of the repo; `//` appears only in templates
  aimed at `web/`.

**Commit message format**

- Templates do not carry a commit line by default. Where one appears, the observed
  convention is `agent: <slug>` (the executor's commit format); conventional-commit
  forms `feat(scope): subject` appear in templates aimed at merged web work.

**Whole-body properties**

- Plain text, no markdown fences, no trailing blank line.
- Nine lines in the default (no-hits) case.
- A body that is hex characters and whitespace only is a binary `PATCH TEMPLATE` stub,
  not a readable template — the quarantine gate rejects exactly this shape.

## Well-formedness

`patch_template_structure.observe()` reports `well_formed = True` only when the body has
a `PATCH TEMPLATE <id>` header, at least one label, at least one numbered slot, and is
not a hex-only stub. `compare([...])` diffs several bodies and returns which structural
keys `varies` — use it to catch builder drift before it reaches consumers.
