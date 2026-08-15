PROJECT: beethoven

- id: improve-compliance-evidence-vault
  title: improve-compliance-evidence-vault
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_compliance_evidence_vault.py
  prompt: |
    Implement the compliance evidence vault: a staged capture workflow for policy snapshots, filing confirmations, approval-chain exports, and risk-history exports; immutable content-addressed manifests; retention/legal-hold metadata; secret/PII redaction; and restricted retrieval. Keep evidence_collector path confinement. Add tests for staging, tamper detection, redaction, and traversal rejection.
    
    Queue context: Follow-up identified during Round 8 audit: collector now restricts paths but needs managed capture and retention infrastructure.
