# Contract verifiers

Seven `verify-*.mjs` scripts live here. Until 2026-08-23 **none of them ran**:
they were not in `package.json`, not in `ci.yml`, not in any workflow. Written
once, referenced by nothing. Five have since rotted, which is what happens to a
check nobody executes.

`prebuild` now runs the two that hold. The other five are real failures worth
fixing, not noise to suppress — but they are not in the blocking path, because a
prebuild that is red on arrival gets bypassed, and then none of it protects
anything.

    npm run verify:contracts   # blocking. runs in prebuild.
    npm run verify:all         # everything, including the five below.

## Blocking

| script | asserts |
|---|---|
| `verify-navigation-contract.mjs` | the 12 canonical destinations exist, in order, with their compatibility aliases, at contract v2 |
| `verify-admin-index.mjs` | every screen under `pages/admin/` is listed in `config/adminTools.ts`, and every listed tool has a page |

## Failing — each is a real defect

| script | failure | shape |
|---|---|---|
| `verify-embed-contracts.mjs` | `Embed contract failed for: apparently` | assertion. The apparently embed contract genuinely does not hold. |
| `verify-experience-contracts.mjs` | `legacy palette found #6557d8` | assertion. Design tokens drifted; a legacy hex is still in the tree. |
| `verify-dependency-graph.mjs` | crashes | the script itself throws before asserting anything. |
| `verify-journey-contracts.mjs` | crashes | same. Note the journey contract is half of what `DEPLOYED_AND_VERIFIED` requires, and `journey_contract_runs` has 0 rows — this verifier and that empty table are the same gap seen from two directions. |
| `verify-dashboard-browser.mjs` | needs a browser | requires Playwright; belongs in `test:e2e`, not `prebuild`. |

Fix one, move it into `verify:contracts`. Do not move a failing one in, and do
not delete a check to make the column green.
