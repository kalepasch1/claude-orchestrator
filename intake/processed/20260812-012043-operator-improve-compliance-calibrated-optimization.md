PROJECT: beethoven

- id: improve-compliance-calibrated-optimization
  title: improve-compliance-calibrated-optimization
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_filing_optimizer_calibration.py
  prompt: |
    Replace heuristic-only filing amendment and batching estimates with a calibrated, explainable optimizer trained from approved historical filing outcomes. Add feature/provenance storage, validation split, fallback behavior when sample size is insufficient, and no claims of savings unless measured. Integrate output with the evidence trail and approval workflow. Add tests for calibration threshold, fallback, deadline prioritization, and reproducible recommendations.
    
    Queue context: Follow-up identified during Round 8 audit: optimizer is deterministic heuristics, not an ML model.
