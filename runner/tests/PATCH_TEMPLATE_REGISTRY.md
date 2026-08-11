# Patch template registry

Maps each patch-template hash to its owner module and acceptance test so
repair/recovery passes can reuse existing work instead of reconstructing it.
Templates themselves are stored in the `knowledge` table with a fail-soft
fallback at `.runtime/patch_templates.jsonl`; resolve one programmatically
with `patch_templates.lookup(template_id)`.

| Template id  | Owner module               | Acceptance test                                              |
|--------------|----------------------------|--------------------------------------------------------------|
| 95fc17a356b7 | `runner/patch_templates.py` (`lookup`) | `runner/tests/test_template_95fc17a.py`          |
| 4fa4039b57dc | `runner/patch_transplant.py` | `runner/tests/test_patch_transplant_relfix_kalepasch_com_4fa4039b57dc.py` |
| ce2e8dcd7954 | `runner/patch_transplant.py` | `runner/tests/test_patch_transplant_relfix_kalepasch_com.py` |
| 918597e30434 | `runner/patch_templates.py` (`lookup`, `pre_claim_hook`) — branch-recovery template | `runner/tests/test_template_918597e3.py` |

When adding a new hash-scoped test, add a row here in the same commit.
