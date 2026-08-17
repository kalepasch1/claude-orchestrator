PROJECT: beethoven

- id: improve-compliance-durable-event-router
  title: improve-compliance-durable-event-router
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_compliance_event_router.py
  prompt: |
    Implement a durable, cross-process compliance event router. Replace the current in-process subscriber-only fan-out with an idempotent persisted outbox, consumer offsets, retry/dead-letter handling, and deterministic event replay. Preserve the existing events.py and evidence_bus.py receipts. Add tests proving exactly-once handler effects across a process restart and failed handler retry.
    
    Queue context: Follow-up identified during Round 8 audit: current local subscribers do not coordinate multiple runner processes.
