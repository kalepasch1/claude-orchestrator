PROJECT: beethoven

- id: improve-compliance-api-auth-tenancy
  title: improve-compliance-api-auth-tenancy
  material: no
  model: 
  submitted-by: Codex operator-directed remediation
  depends: []
  proof: runner/tests/test_compliance_api_auth.py
  prompt: |
    Harden compliance_api_gateway.py for production use: enforce authenticated caller identity, derive tenant identity from the principal rather than request body, authorize every app resource, apply request size/rate limits, remove permissive CORS, and add structured audit logs. Keep it loopback-safe until an authentication adapter is configured. Add rejection and cross-tenant access tests.
    
    Queue context: Follow-up identified during Round 8 audit: API tenancy is caller-supplied and needs an authenticated boundary.
