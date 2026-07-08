PROJECT: claude-orchestrator

# Orchestrator-self. Reframes the approval floor to CADE-scored risk bands + per-feature INSTANT REPEAL.
# Builds ON existing modules: committees.py (CADE), constitution.py, legal_triage.py, approval_policy.py,
# approval_merge.py, blast_radius.py, kill_switch.py, controls table, provenance.py, recipes/add-feature-flag.md.
# Owner policy: do NOT block unless CADE says risk is genuinely high; auto-implement below materiality;
# make anything CADE-flagged instantly repealable with zero impact on other code.

- id: cade-risk-score
  title: Single numeric CADE risk score (0-100) + bands on every change/card
  material: yes
  model: opus
  depends: []
  proof: `python3 -m pytest runner/tests/test_cade_risk.py` exits 0
  prompt: |
    Add runner/cade_risk.py `score(card_or_diff) -> {risk: 0..100, drivers:[...], band}` derived from the
    EXISTING CADE stack — do not reinvent: committees.py consensus distribution + severity×plausibility +
    uncertainty band, constitution.evaluate() must_gate, legal_triage level (routine/elevated/novel), and
    compliance-as-tests results (see compliance-gate task). Map to bands:
      LOW    risk < 50   -> auto-implement, normal auto-merge
      ISOLATE 50..70      -> auto-implement, but REQUIRES the instant-repeal isolation harness
      GATE   risk > 70    -> materially high -> route to human/counsel CADE review (the ONLY blocking case)
    Thresholds come from owner_model keys (CADE_ISOLATE_MIN=50, CADE_GATE_MIN=70) so they're tunable.
    Persist cade_risk / cade_band / cade_drivers on the approval row (add columns via migration). Calibrate
    with committees' existing calibration weights. Add runner/tests/test_cade_risk.py: novel-regulated => GATE;
    routine/boilerplate => LOW; borderline posture-adjacent => ISOLATE; drivers are populated.

- id: cade-banded-policy
  title: Rewire the approval/merge gate to CADE bands (stop blanket legal blocking)
  material: yes
  model: opus
  depends: [cade-risk-score]
  proof: `python3 -m pytest runner/tests/test_cade_bands.py` exits 0
  prompt: |
    Update approval_policy.sweep() + the runner merge gate (runner.py legal_counsel_required path,
    approval_merge.py) to key off cade_band instead of blanket "legal => block":
      LOW    -> auto-approve + auto-merge (unchanged happy path).
      ISOLATE-> auto-approve + auto-merge ONLY if the isolation harness verified the change is
                independently repealable (else hold as 'needs-isolation', not a legal gate).
      GATE   -> the only human-gated case: enrich as today (narrow question + flexible alternatives).
    KEEP the constitution.py HARD FLOOR that no score can override: autonomous money movement, external
    filing/sending, credential/secret changes ALWAYS gate (constitution_gate). Nothing else blocks unless
    risk>70. Every auto decision keeps writing decided_by + a digest row + a provenance cert. Add
    runner/tests/test_cade_bands.py covering all three bands + the hard floor overriding a LOW score.

- id: flags-runtime
  title: Runtime feature-flags table + tiny client (repeal without redeploy)
  material: yes
  model: sonnet
  depends: []
  proof: `python3 -m pytest runner/tests/test_flags.py` exits 0
  prompt: |
    What makes repeal INSTANT: add a `feature_flags` table {slug, project, enabled default true, updated_by,
    updated_at, reason} + runner/flags.py get/set/list. Products read flags at runtime (cached, short TTL) so
    flipping a flag OFF disables a feature with NO redeploy and NO interruption to other code. Emit a small
    per-repo "flag client" task to each product's intake (a 20-line typed helper reading feature_flags).
    Default-ON for repealable features. Add runner/tests/test_flags.py for get/set/default/precedence.

- id: instant-repeal-isolation-harness
  title: Enforce that CADE-ISOLATE changes ship as independently repealable, zero-blast-radius units
  material: yes
  model: opus
  depends: [cade-banded-policy, flags-runtime]
  proof: `python3 -m pytest runner/tests/test_isolation_harness.py` exits 0
  prompt: |
    THE CORE of the owner ask. For any change in the ISOLATE band (opt-in for higher), enforce at
    verify-time that it is instantly repealable with zero impact on other code:
      (a) all new entrypoints are gated behind a named flag `repealable:<slug>` (default ON) via flags.py;
      (b) blast_radius.radius_after() shows ZERO inbound dependents on the new code OUTSIDE the flagged
          module/entrypoints — i.e. nothing else imports it un-flagged; FAIL the gate if the change leaks a
          hard dependency into shared code (force the agent to re-scope behind the flag);
      (c) register it in a `repealable_features` table {slug, flag, project, files[], commit, cade_risk,
          status, created_at};
      (d) implement repeal(slug): flip the flag OFF instantly, and PROVE zero side effects by re-running the
          tests of the dependent set (radius) and confirming still-green + no behavior change outside `files[]`.
          Optionally also revert the isolated commit; but flag-off alone must fully neutralize it.
    Add runner/isolation.py + migration + runner/tests/test_isolation_harness.py: a change that leaks a
    dependency into shared code FAILS the harness; a properly flag-isolated change registers and repeals with
    proven zero blast radius.

- id: feature-repeal-console
  title: Console "Repealable Features" panel — one-click instant repeal per feature
  material: yes
  model: sonnet
  depends: [instant-repeal-isolation-harness]
  proof: `cd web && npx nuxi typecheck` exits 0
  prompt: |
    Add a "Repealable Features" panel to web/pages/index.vue listing repealable_features with each feature's
    CADE risk, driver summary, files, and a one-click REPEAL (calls flags set enabled=false) + RESTORE, plus
    the blast-radius=0 proof and the provenance cert link. This extends kill_switch (project/global) down to
    the individual feature so you can remove any CADE-flagged capability post-implementation without touching
    other code or interrupting deploys. Reuse existing supabase/decide patterns. Verify with nuxi typecheck.

- id: compliance-as-tests-gate
  title: Compliance-as-tests registry + merge gate that feeds CADE
  material: yes
  model: opus
  depends: [cade-risk-score]
  proof: `python3 -m pytest runner/tests/test_compliance_gate.py` exits 0
  prompt: |
    Formalize posture-grep into a real gate. Add a compliance-suite registry: each product declares a named
    executable posture-invariant suite (see the per-product apparently/tomorrow compliance-as-tests tasks).
    The runner verify step runs the touched product's compliance suite; ANY failure (a) BLOCKS the merge and
    (b) forces cade_risk to GATE (>70) with the failing invariant as a driver. A passing suite lowers risk.
    This makes the legal/regulatory posture un-regressable by construction. Add
    runner/tests/test_compliance_gate.py: a diff that breaks a registered posture invariant is blocked and
    scored GATE; a compliant diff passes.

OPERATOR:
  - Tune CADE_ISOLATE_MIN (50) and CADE_GATE_MIN (70) in owner_model once you see a few weeks of scored items.
  - The GATE band (>70) is the only thing that will email/hold you — expect that set to be small.
  - Repeals are logged to provenance; review the Repealable Features panel periodically to sunset dark features.
