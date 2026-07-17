# Security Checklist — Canary Hygiene

Quick-reference for canary task reviewers.

## Pre-merge checks

1. No secrets, credentials, or API keys introduced
2. No dependency changes (package.json, yarn.lock untouched)
3. No billing, legal copy, or product behavior changes
4. Change is doc-only, test-only, or trivially safe code hygiene
5. Existing tests still pass (`npm test`)

## Scope boundaries

- Safe: comments, JSDoc, README updates, test descriptions, lint fixes
- Unsafe: new dependencies, env vars, API endpoints, schema changes
