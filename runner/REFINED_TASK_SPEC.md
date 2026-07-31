# Refined Task Spec: E2E Smoke Test Refactor

**Task ID:** `backlog-batch-darwn-5b34a9d-slice-4` (recovery/rework)  
**Project:** DARWN Frontend (apparently repo)  
**Date:** 2026-07-30  
**Status:** Implementation (shelved due to low EV; resuming with smallest delta)

---

## Objective (Plain English)

Refactor an oversized, flaky E2E test suite (`tests/e2e/hive-usable.spec.ts`, currently 528 lines) into a minimal smoke test that validates two core frontend workflows:
1. Exposure risk preview form (regulatory hive feature)
2. What-if banned scenario analyzer

**Why:** Current test times out at 300s (Playwright limit) due to 16+ tests + permissive selectors + slow retries. A 3-test focused suite will run in <120s, reduce flakiness, and clarify acceptance criteria.

---

## Scope

**Files In Scope:**
- `tests/e2e/hive-usable.spec.ts` (primary target: reduce 528 lines → ~150 lines)
- `tests/e2e/fixtures/auth.ts` (keep as-is; mock auth injection works)
- `playwright.config.ts` (validate timeout settings)

**Files Out of Scope:**
- `/hive/facts` page (regulatory facts browsing—not yet implemented; skip tests)
- Other E2E suites (`/tests/e2e/**/*.spec.ts`)
- Unit/integration tests (this is usability validation only)

**Deployment Gate:**
- Build must pass: `npm run build`
- Tests must pass: `npx playwright test tests/e2e/hive-usable.spec.ts --config=playwright.config.ts`
- No direct production deploy required (it's a test refactor, not a feature)

---

## Acceptance Criteria

### Test 1: Exposure Tool Workflow ✓
- **File:** `tests/e2e/hive-usable.spec.ts` lines ~15–60
- **What it does:** Submits exposure preview form with explicit values, validates response
- **Pass condition:** Form submits → API responds with results OR error message within 10s
- **Timeout:** 30s per test

### Test 2: What-If Banned Workflow ✓
- **File:** `tests/e2e/hive-usable.spec.ts` lines ~60–120
- **What it does:** Toggles scenario signals, runs what-if analysis, validates UI response
- **Pass condition:** Form submits → results section appears OR error message within 10s
- **Timeout:** 30s per test

### Test 3: Cross-Navigation ✓
- **File:** `tests/e2e/hive-usable.spec.ts` lines ~120–150
- **What it does:** Navigates between `/hive/exposure` and `/hive/what-if` pages
- **Pass condition:** Each page loads within 5s; no 404, no unhandled exceptions
- **Timeout:** 20s total

### Proof of Completion
```bash
npm run dev &                                              # Start dev server
npx playwright test tests/e2e/hive-usable.spec.ts --config=playwright.config.ts
# Expected output:
# ✓ 3 passed (120s)
# Exit code: 0
```

---

## Key Decisions & Resolutions

| Ambiguity | Resolution | Rationale |
|-----------|-----------|-----------|
| **URL paths** | `/hive/exposure`, `/hive/what-if`; skip `/hive/facts` | Facts feature not implemented; routes confirmed in codebase |
| **Form submission** | HTML button click (not AJAX); POSTs to `/api/hive/*-preview` | Simpler to test; matches Playwright baseline patterns |
| **Result visibility** | Specific locators (no fuzzy `text=` chains); error paths pass test | Permissive selectors were root cause of flakiness |
| **Seeded data** | No pre-seeding; tests use explicit inline values | Usability ≠ API correctness; API tests belong elsewhere |
| **Error handling** | If API fails, test detects error UI and passes | Proof that page responds; don't hide failures with `.catch()` |
| **Timeouts** | 10s for API response, 30s per test, 120s total | Previous 15s+retries caused 300s timeout |
| **Test count** | 3 tests (down from 16+) | Smoke test: core workflows only; depth is unit/integration scope |
| **Auth** | Mock session injected into localStorage via `auth.ts` | Proven pattern; no Supabase integration in E2E |

---

## What to Keep / What to Cut

### Keep ✓
- `e2e/fixtures/auth.ts` (mock auth injection)
- `playwright.config.ts` baseURL and dev server startup
- Form fill patterns: `input.fill()`, `checkbox.check()`, `select.selectOption()`
- Locator strategies for buttons and headings

### Cut ❌
- All 8 "regulatory facts browsing" tests (facts feature not implemented)
- Overly permissive selectors (`.hasText()` chains trying 5+ alternatives)
- Nested `.catch(() => false)` chains (hide failures, break debugging)
- Tests for "rapid interactions", "network timeouts", "no required fields"
- Session persistence test (auth fixture already proves this)
- Form state toggling tests (not core usability)

---

## Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Test count | 3 | 16+ ❌ |
| Lines | ~150 | 528 ❌ |
| Runtime | <120s | >300s ❌ |
| Flakiness | 0% (specific locators) | High ❌ |
| Success/Failure clarity | High (explicit steps) | Low ❌ |

---

## Implementation Path

1. **Inspect** the existing `tests/e2e/hive-usable.spec.ts` and identify what to keep
2. **Rewrite** tests 1–3 with specific locators and clear step descriptions
3. **Remove** all tests beyond the 3 core workflows
4. **Validate** locators against live `/hive/*` pages (if running `npm run dev`)
5. **Test** with: `npx playwright test tests/e2e/hive-usable.spec.ts`
6. **Commit** with message: `fix(e2e): refactor hive-usable smoke test (3 tests, <120s, specific locators)`

---

## Related Artifacts

- **REFINED_E2E_SPEC.md** (this directory): Detailed behavioral spec for each test
- **tests/test_relfix_pareto_2080_07171927_comprehensive.py**: Comprehensive test suite reference
- **Branch:** `agent/backlog-batch-darwn-5b34a9d-slice-4` (prior work; inspect before starting)

---

## Success Definition

**DONE when:**
- [ ] Test file reduced to ~150 lines
- [ ] All 3 tests pass consistently (0% flakiness)
- [ ] Runtime <120s total
- [ ] No `.catch()` chains or fuzzy selectors
- [ ] Commit authored as `kalepasch1 <kalepasch@gmail.com>` on task branch
- [ ] Build passes: `npm run build`
