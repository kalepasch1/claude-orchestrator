# Security-Class Task Test Hygiene

## Purpose

Document the minimum test expectations for tasks classified as
`task_class: security` by the preflight triage, so QA panelists and
canary probes can verify coverage without manual inspection.

## Checklist for security-class changes

1. **No new secrets in source** — `grep -rn` for patterns matching
   `sk-`, `ghp_`, `Bearer `, `password=` must return zero new hits
   outside `.env.example`.
2. **Fail-soft on missing credentials** — the changed module must not
   raise an unhandled exception when its expected env var is absent;
   it should log a warning and degrade gracefully.
3. **No outbound calls to untrusted hosts** — any new `requests.get/post`
   or `urllib` call must target a host already in the project's
   allowlist (Supabase, GitHub API, model provider endpoints).
4. **Diff size sanity** — security patches should be small and auditable.
   Flag any security-class PR exceeding 200 changed lines for manual
   owner review.

## Non-goals

This checklist is documentation only. It does not modify any runtime
code, secrets, dependencies, or product behavior.
