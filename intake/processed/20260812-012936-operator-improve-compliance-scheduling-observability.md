PROJECT: beethoven

- id: improve-compliance-scheduling-observability
  title: improve-compliance-scheduling-observability
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_compliance_periodic_jobs.py
  prompt: |
    Wire compliance scanners, anomaly checks, scorecard refreshes, and evidence outbox flushing into periodic.py with documented intervals, per-job locks, metrics, alert routing, and no protected-state mutation. Add a health/readiness endpoint reporting backlog age, outbox failures, consumer lag, and data freshness. Add tests for job registration, lock behavior, and safe failure handling.
    
    Queue context: Follow-up identified during Round 8 audit: modules have an API surface but no production periodic scheduling or operational SLOs.
