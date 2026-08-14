# Consolidating duplicated code: the pattern this repo actually merged

**Source note.** The task named branch `beethoven/recover-missing-branch-relfix-beethoven-07071626`
as the successful solve to extract from. That branch does not exist locally or on `origin`
(`git branch -a | grep 07071626` is empty; only `recovery-intent-stub:` commits mention the slug).
Rather than describe a branch nobody can open, this documents the pattern from the three
**merged commits on `master`** that actually did this work, all reproducible today:

| Commit | What it consolidated |
|---|---|
| `b578b67a` | duplicate queue rows — *runtime* duplicates |
| `e307b7bb` | duplicate task inserts — the *source* of duplicates |
| `4716945b` | four copies of one identity expression — *literal* duplicated code |

The three are one pattern applied at three depths, and the order matters.

---

## The pattern in four steps

### 1. Name the canonical thing, and make it a function

Duplication is almost never "the same lines twice." It is *the same decision* re-derived in
several places, and the copies drift. `4716945b` is the clean case: repository identity was
computed inline four times in `runner/proof_graph.py`, so `.`, a relative path, a symlink and a
hook's absolute path each produced a different identity — and the release proof they keyed
silently fragmented.

Before — the decision, inlined, four times:

```python
row = {"repo": os.path.basename(repo.rstrip(os.sep)), ...}
...
row = {"repo": os.path.basename(repo.rstrip(os.sep)) if repo else release.get("project"), ...}
...
capsule = hashlib.sha256(json.dumps({"repo": os.path.basename(repo.rstrip(os.sep)), ...}))
```

After — one canonical definition, every call site delegating to it:

```python
def _canonical_repo(repo: str) -> str:
    """One stable identity for '.', relative paths, symlinks, and hook absolute paths."""
    return os.path.realpath(os.path.abspath(repo or "."))


def _repo_name(repo: str) -> str:
    return os.path.basename(_canonical_repo(repo).rstrip(os.sep))
```

```python
row = {"repo": _repo_name(repo), ...}
row = {"repo": _repo_name(repo) if repo else release.get("project"), ...}
canonical = _canonical_repo(repo)
capsule = hashlib.sha256(json.dumps({"repo": _repo_name(canonical), ...}))
```

**What was kept canonical:** the *normalized* form, not whichever copy happened to be first.
`basename(rstrip(sep))` was the incumbent and it was the buggy one. The extracted helper added
`realpath(abspath(...))` — consolidation was the moment the correct definition was decided, not
a mechanical hoist of existing text.

**How references were updated:** every call site, in the same commit, with no compatibility
shim and no second spelling left behind. A consolidation that leaves one caller on the old path
has not removed the duplication; it has added a third variant.

### 2. Put the key in the key — do not over-collapse

The failure mode of de-duplication is collapsing things that only *look* alike. `e307b7bb`
handles it explicitly: slugs are normalized to a base intent, but `target_path` stays in the
dedup key so two parallel subtasks against different files are not merged into one.

```python
def normalize_slug(slug: str) -> str:
    """Collapse a slug to its base intent by repeatedly stripping fan-out and
    version suffixes (handles stacked suffixes like '-slice-3-slice-4')."""
    s = (slug or '').strip().lower()
    prev = None
    while s != prev:                     # stacked suffixes need a fixpoint, not one pass
        prev = s
        s = _FANOUT_SUFFIX.sub('', s)
        s = _TRAILING_VER.sub('', s)
    return s


def intent_key(project_id, slug, target_path=None) -> str:
    """target_path is part of the key so distinct targets under the same base
    intent are NOT merged (avoids over-collapse)."""
    return '%s::%s::%s' % (project_id or '', normalize_slug(slug), (target_path or '').strip())
```

Two things to copy here. The **fixpoint loop**: real-world duplication stacks
(`-slice-3-slice-4`), and a single-pass strip leaves half the duplicate behind. And the
**deliberately-retained discriminator**: write down, in the docstring, what you refused to
collapse and why. That comment is what stops the next pass from "simplifying" the key.

### 3. Close the tap before bailing the boat

`b578b67a` removed duplicate rows; `e307b7bb` removed the ability to create them, by routing
every insert through one chokepoint:

> "Every task insert SHOULD route through `enqueue_task` so retries, absorption re-routes and
> decomposition slices coalesce onto ONE open row instead of minting the `-slice-N` /
> duplicate-intent fan-out that is ~42% of the table."

Cleanup without a chokepoint regenerates the duplicates on the next run. Chokepoint without
cleanup leaves the existing mess. Both are needed, and the chokepoint should land first or
alongside — never after.

### 4. Consolidate by *pointing at the keeper*, never by deleting

`b578b67a` is the template for what to do with the losing copy. It does not delete the duplicate
and it does not spawn a second writer. It picks the oldest active row as keeper, moves the
duplicate to `DECOMPOSED`, records a dependency on the keeper, and writes an audit note naming
the id it was folded into:

```python
# The queue has a uniqueness guard for active slugs. A rejected update
# therefore usually means this exact improvement already has a live
# recovery row. Consolidate the audited duplicate instead of spawning a
# second writer or retrying it forever.
keepers = db.select("tasks", {
    "select": "id,slug,state",
    "slug": f"eq.{row.get('slug')}",
    "state": "in.(QUEUED,RUNNING,RETRY,DONE)",
    "order": "created_at.asc", "limit": "1",       # oldest wins — deterministic keeper
}) or []
if keepers:
    keeper = keepers[0]
    duplicate_note = (
        f"{RECOVERY_MARK} {now}: duplicate audit row consolidated into active "
        f"task {keeper.get('id')} ({keeper.get('state')}); no second writer created. "
        f"Prior note: {prior_note}"
    )[:4000]
    db.update("tasks", {"id": row["id"], "state": "PHANTOM_UNVERIFIED"}, {
        "state": "DECOMPOSED", "note": duplicate_note,
        "deps": [keeper.get("slug")],
    })
```

Note the compare-and-set match (`{"id": ..., "state": "PHANTOM_UNVERIFIED"}`): the row is only
folded if it is still in the state that was observed. A blind update races the very concurrency
that produced the duplicate.

And the counts stay separate — `recovered` and `consolidated` are reported and returned
independently, so "we fixed 40" never quietly means "we deleted 39 and fixed one."

---

## The test that proves it

Each of the three commits changed tests in the same commit as the code, and the assertion is
always **that the second copy was not created**, not merely that the first one works:

```python
def test_active_slug_consolidates_duplicate_without_second_writer():
    ...
    assert result["recovered"] == 0
    assert result["consolidated"] == 1
    _match, values = database.update.call_args.args[1:]
    assert values["state"] == "DECOMPOSED"
    assert values["deps"] == ["dropbox-same"]
```

A test that only exercises the canonical helper passes just as happily when a caller is still
on the old inline copy. Assert on the absence of the duplicate.

---

## Checklist

- [ ] The canonical definition is **correct**, not merely incumbent — fix it as you extract it.
- [ ] **Every** reference updated in the same commit; no shim, no second spelling.
- [ ] The dedup key names what you refused to collapse, in a docstring.
- [ ] Normalization reaches a fixpoint; suffixes stack.
- [ ] The tap is closed (chokepoint) as well as the boat bailed (cleanup).
- [ ] Losing copies are **pointed at the keeper** with an audit note, not deleted.
- [ ] Keeper selection is deterministic (oldest active) and the update is compare-and-set.
- [ ] Cleanup and consolidation counts are reported separately.
- [ ] A test asserts the duplicate was *not* created.
