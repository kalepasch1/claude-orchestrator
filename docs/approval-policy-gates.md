# Approval Policy — Gate Reference

`runner/approval_policy.py` implements the approval gate for the orchestrator.
Only a narrow set of issues require human approval; everything else auto-approves.

## Gate Categories

**LEGAL-GATE (requires owner approval):**
- `kind='legal'` with `legal_risk_level='novel'`
- Changes that affect licensing, registration, custody, transmission,
  regulated advice, or underwriting posture

**AUTO-APPROVE (no human needed):**
- Routine code changes, doc updates, test hygiene
- Legal items already cleared by `legal_triage` as routine
- All non-legal task kinds without elevated risk

## Card Design Principle

When a card IS gated, it is scoped to the specific legal question with
2–4 flexible options. Never a wall of text, never a bare yes/no.
