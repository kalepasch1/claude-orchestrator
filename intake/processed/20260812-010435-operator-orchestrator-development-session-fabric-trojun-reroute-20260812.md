PROJECT: trojun

- id: contracts-trojun-development-session-embed
  title: Replace the superseded Illuminati session contract with the canonical Trojun contract
  material: yes
  model: opus
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [beethoven:shared-development-terminal-sdk-and-madeus-client, beethoven:foulkon-illuminati-apparently-steering-hooks]
  proof: the Trojun adapter contract tests pass and risk guidance is a signed receipt rather than executable authority
  prompt: |
    This is the exact successor to superseded task contracts-illuminati-development-session-embed after project illuminati was retired into Trojun. Define Trojun's two bounded roles: a signed Illuminati/Foulkon risk-steering adapter into the shared broker and a thin project-scoped terminal client. Specify auth, decision schema/version, latency, fallback, override audit, proof display, and strict separation from shell/release authority. Limit scope to contracts and tests. Preserve a durable trace to superseded task id f7161a40-ca2f-4332-940b-2bffe2a6eb1a in the result.

- id: adopt-shared-development-terminal-in-trojun
  title: Replace Trojun's missing WebSocket and demo fallback with the shared session client
  material: yes
  model: sonnet
  submitted-by: Codex operator-directed orchestrator remediation
  depends: [contracts-trojun-development-session-embed, beethoven:shared-development-terminal-sdk-and-madeus-client]
  proof: Trojun typecheck/unit/e2e suites pass; disconnect never loads demo agents or deployments in production
  prompt: |
    This is the exact successor to superseded task adopt-shared-development-terminal-in-illuminati after project illuminati was retired into Trojun. Remove the nonexistent /api/terminal/ws loop, demo-state production fallback, and fake cascade responses. Adopt the shared authenticated session client with cursor replay and explicit UNKNOWN/OFFLINE states. Render real Illuminati/Foulkon steering decisions and proof receipts. Add tests for connection failure, resume, duplicate event suppression, signed decision display, and absence of demo data outside fixtures. Preserve a durable trace to superseded task id 77e3d562-7b71-42a7-a2ef-cf8b4105244b in the result.
