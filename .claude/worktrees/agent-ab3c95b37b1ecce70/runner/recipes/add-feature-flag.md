# Recipe: add a feature flag

Introduce a feature flag `{{flag}}` so `{{feature}}` can ship dark and be enabled safely.

Steps:
1. Add `{{flag}}` to the project's flag config (env var or flags table), default OFF.
2. Gate the `{{feature}}` code paths behind the flag; ensure OFF = current behavior.
3. Add a test for both flag states.
4. Document the flag in CLAUDE.md / README.

Acceptance: with the flag OFF all existing tests pass unchanged; with it ON the new
`{{feature}}` path is exercised by a test.
