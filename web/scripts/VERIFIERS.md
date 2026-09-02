# Contract verifiers

Seven `verify-*.mjs` scripts live here. Until 2026-08-23 **none of them ran**:
not in `package.json`, not in `ci.yml`, not in any workflow. Written once,
referenced by nothing.

    npm run verify:contracts     # BLOCKING. runs in prebuild. four checks.
    npm run verify:integration   # networked. not blocking. see below.
    npm run verify:all           # everything, including the two known failures.

## Blocking — hermetic, and green

| script | asserts |
|---|---|
| `verify-navigation-contract.mjs` | the 12 canonical destinations exist, in order, with their compatibility aliases, at contract v2 |
| `verify-admin-index.mjs` | every screen under `pages/admin/` is listed in `config/adminTools.ts`, and every listed tool has a page |
| `verify-dependency-graph.mjs` | `@nuxtjs/supabase`, `typescript` and `vue-tsc` are pinned exactly, H3 stays on v1, and one TypeScript resolves across the tree |
| `verify-journey-contracts.mjs` | 5 journeys and 13 critical action surfaces still offer what they promise |

Hermetic is the entry criterion, not a nice-to-have. A blocking check that can
fail because a remote host is unreachable is a check people learn to bypass, and
a bypassed prebuild protects nothing.

## Not blocking

| script | why |
|---|---|
| `verify-embed-contracts.mjs` | makes live HTTP requests to nine deployed projects. Currently red: `apparently` returns `HTTP ERR · blocked`, because that project has no public custom domain and its only URL is SSO-gated. A real defect, and not one a build should stop for. `npm run verify:integration`. |
| `verify-dashboard-browser.mjs` | needs Playwright and a running server. |

## Open — a real failure, and a decision rather than a fix

`verify-experience-contracts.mjs` reports `legacy palette found #6557d8`.

The hex is a purple accent in `components/CadeOperatingSystem.vue`,
`components/ConnectorOptimizationPanel.vue` and `pages/connectors.vue` — eyebrow
text, progress-bar fills, icon grounds. `config/experience-contracts.json`
sanctions `#194c36` and `#fff`.

Substituting deep green for purple across three surfaces changes how they look.
That is a design decision and it is left to a person. The verifier is right that
the drift exists; it should not be silenced, and it is not in the blocking path
until the colour question is settled.

## What was wrong with the earlier note in this file

It recorded `verify-dependency-graph` and `verify-journey-contracts` as
"crashes". They were not crashing. Each was throwing a bare `Error` at module
top level with its own assertion message, so a real finding arrived wearing a
stack trace and was filed as a broken script. Both were saying something true:

  * the dependency pins had drifted from exact to caret, and the
    `overrides.typescript` pin had been dropped entirely — on a toolchain where
    vue-tsc is version-fragile against typescript
  * the front door's `"What should we accomplish?"` was no longer in
    `pages/index.vue`

The second one turned out to be the verifier's fault rather than the app's: the
prompt had been extracted into `components/UniversalCommand.vue`, which
`layouts/default.vue` renders on every page. The journey was intact. A contract
that asserts a string in one FILE breaks on any refactor that moves it, and a
check that goes red for a refactor is one people learn to delete. It now
resolves a marker through the file, the components it renders, and its layout —
and prints which file satisfied it, so nothing is loosened silently.
