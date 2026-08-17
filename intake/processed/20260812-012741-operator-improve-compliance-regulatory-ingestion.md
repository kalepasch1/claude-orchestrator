PROJECT: beethoven

- id: improve-compliance-regulatory-ingestion
  title: improve-compliance-regulatory-ingestion
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_regulation_ingestion.py
  prompt: |
    Build approved-source regulatory ingestion for regulation_scanner.py: source registry, robots/terms-aware fetch adapter, content-version storage, change extraction with confidence and provenance, and event publication to the durable compliance event router. Do not scrape or fetch unapproved sources. Add deterministic fixture tests for first observation, meaningful change, unchanged content, and malformed source responses.
    
    Queue context: Follow-up identified during Round 8 audit: scanner is deliberately adapter-only and needs controlled production source integration.
