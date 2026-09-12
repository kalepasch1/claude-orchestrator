# Why merges conflict in `runner/config_consumer.py`

Task: `orch-config-consumption-inspect-conflicting-merge-target-runner-`. Read-only
inspection; no behaviour changed. Measured against `origin/master@5c4eaf2f`.

## Answer in one line

**Three unmerged agent branches each rewrite the same three regions of a 273-line file,
and each is a re-run of the same backlog item.** They do not disagree about behaviour —
they disagree about where the identical idea should live. Any two of them land, the third
conflicts.

## The three branches

Of ~1,806 remote agent branches, exactly three touch this file:

| branch | diff | region touched |
|---|---|---|
| `origin/agent/backlog-batch-beethoven-7b53616-apply-orch-config-patch` | +25/-1 | `@@ -28,13 +28,37` — the module-level import seam and cache constants |
| `origin/agent/backlog-batch-beethoven-e63dfee-apply-orch-config-consumption-patch` | +25/-2 | `@@ -47,17 +47,40` — `_env_number` tail into the `_ConfigConsumer` class header |
| `origin/agent/backlog-batch-beethoven-22ee5bc-remaining-stale-backlog-items` | +28/-8 | `@@ -20,6 +20,13` and `@@ -107,15 +114,28` — imports **and** the `get`/`get_int` accessors |

The slugs give it away: `apply-orch-config-patch`, `apply-orch-config-consumption-patch`,
and `remaining-stale-backlog-items` are three attempts at one backlog item. This is the
duplicate-tree problem `tools/dedupe_agent_branches.py` was written for, except these are
near-duplicates rather than byte-identical, so the detector does not collapse them.

## The conflicting sections, and what they are responsible for

### 1. The optional-import seam (lines 24–28)

```python
try:
    import fleet_control
except Exception:
    fleet_control = None
```

Responsible for: letting a missing or broken config gateway degrade to **env-only**
config instead of an import error, and giving callers and tests a seam to patch. Two
branches rewrite this block, and it is only five lines — so any edit is a whole-hunk
conflict.

### 2. The cache constants (lines 31–32)

```python
DEFAULT_CACHE_TTL_SEC = 60.0
DEFAULT_CACHE_MAX_ENTRIES = 1000
```

Responsible for: bounding how long a config read is trusted and how many keys are held.
`...7b53616` renames these to `_DEFAULT_CACHE_TTL_SEC` (private). That rename is the
sharpest conflict in the set: it is a **public-name change**, so it does not merely
collide textually — whichever branch loses, any code referring to the other spelling
breaks. Nothing on master references the private form.

### 3. The `_ConfigConsumer` accessors (lines ~100–130)

`get`, `get_int`, `get_bool`, `get_float`, each fail-soft, each reading `ORCH_{key}` from
the environment. Responsible for: the entire read path — every consumer of fleet config
goes through here. `...22ee5bc` rewrites this region while `...e63dfee` rewrites the class
header immediately above it, so the two overlap at the boundary.

## Entrypoints that load/validate consumer config

The module's public surface is `load_all`, `get`, `get_int`, `get_bool`, `get_float`,
`load_config`, `invalidate_cache` (lines 227–273). Searching the repo for importers:

* `runner/test_config_consumer.py` — the module's own tests
* `runner/test_canary_deepseek_1.py` — a canary that exercises it

**and nothing else.** No production module in `runner/`, `tools/` or `scripts/` imports
`config_consumer`. It is a seam with tests and no callers — the same shape as
`config_store.py`, `causal_feedback.py` and `error_classifier.py`, each of which was found
this month to have been written, tested, and never wired in.

Validation itself lives in `_env_number` (lines 35–55): casts, enforces a minimum, and on
any failure prints and returns the default rather than raising.

## What follows from this

1. **The conflict is not resolvable by rebasing harder.** Three branches, one idea, one
   file. Pick ONE, land it, and close the other two as duplicates — the same adjudication
   `docs/reconciliation/dedupe-agent-branches.md` applies to byte-identical clusters.
2. **`...7b53616` is the one to scrutinise**, because only it changes a public name
   (`DEFAULT_CACHE_TTL_SEC` → `_DEFAULT_CACHE_TTL_SEC`). Landing it after either sibling
   silently changes the module's surface.
3. **Wiring matters more than the merge.** With no production caller, all three branches
   are arguing about the shape of code nothing executes. Landing any of them changes no
   behaviour until something imports it.

## Reproduction

```bash
git fetch origin
for b in $(git for-each-ref --format='%(refname:short)' refs/remotes/origin/agent/); do
  git diff --quiet origin/master...$b -- runner/config_consumer.py || echo "$b"
done
git diff origin/master...origin/agent/backlog-batch-beethoven-7b53616-apply-orch-config-patch \
  -- runner/config_consumer.py
grep -rln config_consumer runner/ tools/ scripts/
```
