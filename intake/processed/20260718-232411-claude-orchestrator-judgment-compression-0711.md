PROJECT: claude-orchestrator

# Judgment compression — minimize the human-decision surface to genuinely novel/material/irreversible calls, learn the
# operator's past decisions to PRE-DECIDE the rest (proposed, never auto-applied for material items), and measure
# decisions-per-outcome. Verified thin (4 hits). Builds on approvals-concierge (cards -> Macey with context) + the
# 5/95 doctrine. GOVERNANCE: a learned pre-decision is a SUGGESTION with a confidence; material/irreversible/novel items
# ALWAYS require an explicit human tap (never auto-approved). Additive; fail-soft.

- id: operator-preference-model
  title: Learn the operator's decision patterns to pre-fill (not auto-apply) approval cards
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests -q -k preference` exits 0
  prompt: |
    Add runner/operator_preference.py: from the history of approvals/rejections (decision, card features, outcome),
    learn a per-category predictor that, for a NEW card, outputs { suggestedDecision, confidence, similarPriorIds }.
    Rules (fail-closed): NEVER auto-apply for material=yes, irreversible, or novel (no close prior) cards — those always
    require an explicit human tap; only non-material, high-confidence, has-precedent cards may be surfaced as
    "pre-approved, tap to confirm." Emit a decisions-per-outcome metric to the cost/outcome telemetry. Deterministic +
    fail-soft (no model/data -> no suggestion). Add runner/tests/test_operator_preference.py: material card never gets an
    auto-suggestion; a high-confidence non-material card with precedent gets a pre-fill; low-confidence gets none; the
    decisions-per-outcome metric is emitted.

- id: approvals-concierge-compression-ui
  title: Embed pre-decisions + batching into the approvals concierge (fewest-taps surface)
  material: no
  model: sonnet
  depends: [operator-preference-model]
  proof: `cd web && npx nuxi typecheck` exits 0 (or `npm run build` exits 0 if typecheck unavailable)
  prompt: |
    Extend the approvals-concierge surface (web/) so cards carry the operator-preference suggestion + confidence + a
    "why (similar prior)" reveal, group same-kind non-material cards into a single batched "confirm all like this"
    action, and float genuinely novel/material/irreversible cards to the top as the only ones demanding real judgment.
    Show a running "decisions-per-outcome" stat so the compression is visible. Reuse approval-queue components + design
    tokens; sidebar + command-palette entry; no new poll loops. Material/irreversible cards can NEVER be inside a batch
    "confirm all" — enforce in the UI.

OPERATOR:
  - Review the first week of pre-decision suggestions before raising the confidence threshold that lets non-material cards show as "tap to confirm."
