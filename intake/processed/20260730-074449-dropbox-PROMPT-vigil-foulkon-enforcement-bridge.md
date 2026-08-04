# Vigil ↔ Foulkon — Enforcement Bridge (EnforcementSpec population)

Operator directive 2026-07-30. Foulkon options must carry the Vigil ENFORCEMENT lens — distinct
from the exam-flag Monte-Carlo already live: not "will an examiner note it" but "will the
regulator ACT" — probability of enforcement/sanction/adverse action, with severity and horizon.
Schema shipped (`EnforcementSpec` in illuminati `server/utils/rapidGradient.ts`); populate it.

## What to build
1. **Enforcement probability model on Vigil** (reuse what exists — do not rebuild): the sealed-
   prediction infrastructure (`vigil_prospective_predictions` + `vigil_prediction_scores` with
   Brier/log-loss scoring) is the calibration engine; the regulator outcome receipts
   (`vigil_regulator_outcome_receipts`) are the ground truth; enforcement-action histories per
   regulator family/jurisdiction are the base rates. Output per (jurisdiction, violation class):
   p_action (0-1), severity distribution (fine bands / license condition / consent order /
   license risk), horizon (exam-cycle-driven vs complaint-driven), and the basis string.
2. **Sealed predictions as a discipline**: every p_action the bridge serves is REGISTERED as a
   sealed prediction on Vigil (subject digest, model version, outcome window) — so our
   enforcement probabilities build a public-able Brier record exactly like the case-outcome
   predictions (Part 10). The bridge's honesty is measurable.
3. **Export seam**: extend the existing Foulkon snapshot pipeline (orchestrator `foulkon_sync.py`
   reads a Vigil-produced artifact, same pattern as regulator_simulation) with an
   `enforcement_model` section: per (jurisdiction, violation class) rows. Foulkon-side: a
   deterministic matcher (like the examiner-sim seat) attaches EnforcementSpec to options whose
   risk class maps to a modeled violation class — $0, 0ms at query time.
4. **Feedback loop**: regulator portal ingests (exam outcomes, correspondence, actions) →
   outcome receipts → prediction scoring → base-rate refinement → next snapshot. The same loop
   that makes the flag sim converge makes the enforcement model converge.
5. **Display contract**: p_action always carries severity + horizon + basis; never a naked
   percentage. Calibration status shown when available ("model Brier 0.18 over 40 resolved
   predictions") — the number that makes a GC trust a probability.

## Posture
Anonymized/aggregated base rates only (no cross-workspace leakage — Vigil hivemind rules apply);
predictions are about REGULATOR behavior, not customer conduct; no entity ranking, ever.
