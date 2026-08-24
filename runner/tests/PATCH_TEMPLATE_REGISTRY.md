# Patch template registry

Maps each patch-template hash to its owner module and acceptance test so
repair/recovery passes can reuse existing work instead of reconstructing it.
Templates themselves are stored in the `knowledge` table with a fail-soft
fallback at `.runtime/patch_templates.jsonl`; resolve one programmatically
with `patch_templates.lookup(template_id)`.

| Template id  | Owner module               | Acceptance test                                              |
|--------------|----------------------------|--------------------------------------------------------------|
| 95fc17a356b7 | `runner/patch_templates.py` (`lookup`) | `runner/tests/test_template_95fc17a.py`          |
| ae92a40b1d18 | `runner/patch_templates.py` (`find_template`) — slug-keyed resolver for `dependency_stub` | `runner/tests/test_patch_templates_find_template.py` |
| 4fa4039b57dc | `runner/patch_transplant.py` | `runner/tests/test_patch_transplant_relfix_kalepasch_com_4fa4039b57dc.py` |
| ce2e8dcd7954 | `runner/patch_transplant.py` | `runner/tests/test_patch_transplant_relfix_kalepasch_com.py` |
| 918597e30434 | `runner/patch_templates.py` (`lookup`, `pre_claim_hook`) — branch-recovery template | `runner/tests/test_template_918597e3.py` |

When adding a new hash-scoped test, add a row here in the same commit.

## The local fallback store

`patch_templates._store` writes to the `knowledge` table. When that write fails it falls
back to `.runtime/patch_templates.jsonl` on whichever Mac ran the task, and that file is
what `lookup()` and `find_template()` read when the table is unreachable.

Two properties matter, and both are enforced by
`runner/tests/test_patch_template_fallback_store.py`:

* **It is bounded.** `ORCH_PATCH_TEMPLATE_FALLBACK_MAX` (default 500) caps it, pruned
  from the FRONT because readers take the last matching line, so pruning cannot change
  what a reader would have returned. Unbounded, it is a slow leak that every
  dependency-recovery read walks end to end.
* **Falling back is loud.** A template that reached only local disk is invisible to every
  other host, so a recovery pass on another machine will not find it and will rebuild the
  work. `_store` logs a `LOCAL-ONLY` warning naming the template, the slug and the path.
  Treat that warning as "this template is not really stored yet".
