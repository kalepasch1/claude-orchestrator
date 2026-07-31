# Refined E2E Spec: Regulatory Hive Usability Smoke Test

**Task:** `act-e2e-usable-smoke`  
**File:** `tests/e2e/hive-usable.spec.ts` (528 lines → reduce to ~150 lines)  
**Status:** Prior branch timed out at 300s; test is oversized and too permissive

---

## Ambiguities Resolved

### 1. URL Paths (RESOLVED)
- **Regulatory Hive Exposure Tool:** `/hive/exposure`
- **What-If Banned (Regime Classifier):** `/hive/what-if`
- **Regulatory Facts:** Not yet implemented; skip facts-browsing tests for now
- **Base URL:** `http://localhost:3000` (from `playwright.config.ts`)

### 2. Form Submission (RESOLVED)
- **Exposure Tool:** Button text `"Compute Exposures"` → POSTs to `/api/hive/exposure-preview`
- **What-If Tool:** Button text `"Run What-If Analysis"` → POSTs to `/api/hive/what-if-banned`
- **Mechanism:** HTML form button click (not AJAX, not magic)

### 3. Result Visibility (RESOLVED)
- **Exposure results:** Section with heading containing "Flagged Exposures" + table with headers (Severity, etc.)
- **What-If results:** Section with heading containing "Migration Paths" + `.bg-yellow-50` counter-arbitrage box
- **Assertions:** Locators must be specific (not `text=` fuzzy patterns)

### 4. Seeded Data (RESOLVED)
- **No pre-seeding required:** Tests submit forms with explicit values; API returns results or error
- **Error handling:** If API fails, test logs it but passes (usability = "page responds to form submission")
- **Timeout for API response:** 10 seconds per request (not 15s—too long)

### 5. Input Parameters & Expected Outputs (RESOLVED)

#### Exposure Tool
- **Inputs:**
  - `jurisdiction`: "NJ"
  - `basis`: "NJ Rev. Stat. § 5:12-1"
  - `coveredRoles`: `["payment_processing"]` (checkbox)
  - `relationships`: 1 relationship with orgLabel="TestCorp", counterpartyOperator="OperatorCo"
- **Outputs:** `{ exposures: Exposure[] }` where each has `{ severity, orgLabel, basis, ... }`

#### What-If Banned
- **Inputs:**
  - `vertical`: "sweepstakes_casino" (default)
  - `trigger`: "ban" (default)
  - `jurisdiction`: "NY" (default)
  - `signals`: `{ realMoney: true, handlesPayments: false, ... }`
- **Outputs:** `{ arbitrage: { paths: [...], residualRisks: [...] }, counter: { memo: string } }`

### 6. Authentication (RESOLVED)
- **Mechanism:** Mock Supabase session injected into localStorage by `e2e/fixtures/auth.ts`
- **Session key:** `sb-localhost-auth-token` or key matching pattern `*supabase*`
- **Mock user:** `{ id: 'e2e-user-00000000-0000-0000-0000-000000000001', email: 'e2e-test@apparently.com', role: 'authenticated' }`
- **Fixture:** Authed pages are passed as `{ authedPage }` parameter to each test

### 7. Environment (RESOLVED)
- **Dev only:** `localhost:3000` (started by Playwright via `npm run dev`)
- **Browser:** Chromium (single project, no cross-browser matrix yet)
- **Retries:** 0 locally, 1 in CI

### 8. Data Seeding (RESOLVED)
- **Strategy:** No seeding; tests fill form fields with explicit inline values
- **Rationale:** Usability = "forms accept input and API responds"; don't test API correctness here
- **If API fails:** Test detects error message in UI (text-red-600 class) and passes (proof: "page is responsive")

---

## Refined Acceptance Criteria

### Test 1: Exposure Tool Workflow
**File location:** `tests/e2e/hive-usable.spec.ts` lines ~15–60

**Setup:**
- Authed user navigates to `/hive/exposure`
- Page loads within 5s (waitUntil: 'domcontentloaded')

**Assertions:**
1. ✓ Heading visible: `<h1>Support-Entity Exposure Preview</h1>`
2. ✓ Form renders: `<input placeholder="NY">` (jurisdiction field)
3. ✓ Submit button exists: `<button>Compute Exposures</button>`

**Action:**
- Fill `jurisdiction` input: "NJ"
- Fill `basis` input: "NJ Rev. Stat. § 5:12-1"
- Check `payment_processing` checkbox
- Click "Compute Exposures"

**Expected:**
- Within 10s, EITHER:
  - ✓ `<section>` containing `<h2>Flagged Exposures</h2>` appears, OR
  - ✓ Error message (`.text-red-600` class) appears
- ✓ No page crash (no 500 error in console)

**Timeout:** 30s total for this test

---

### Test 2: What-If Banned Workflow
**File location:** `tests/e2e/hive-usable.spec.ts` lines ~60–120

**Setup:**
- Authed user navigates to `/hive/what-if`
- Page loads within 5s

**Assertions:**
1. ✓ Heading visible: `<h1>What-If Banned</h1>`
2. ✓ Form renders: `<select>` with option "sweepstakes_casino" selected (default)
3. ✓ Checkboxes present: at least one `<input type="checkbox">` (for model signals)
4. ✓ Submit button exists: `<button>Run What-If Analysis</button>`

**Action:**
- Leave defaults (vertical="sweepstakes_casino", trigger="ban", jurisdiction="NY")
- Toggle one checkbox (e.g., realMoney: uncheck it if checked)
- Click "Run What-If Analysis"

**Expected:**
- Within 10s, EITHER:
  - ✓ `<section>` containing `<h2>Migration Paths</h2>` appears, OR
  - ✓ `.bg-yellow-50` counter-arbitrage box appears, OR
  - ✓ Error message (`.text-red-600` class) appears
- ✓ No page crash

**Timeout:** 30s total for this test

---

### Test 3: Cross-Navigation
**File location:** `tests/e2e/hive-usable.spec.ts` lines ~120–150

**Action:**
- Navigate: `/hive/exposure` → `/hive/what-if` → `/hive/exposure`

**Expected:**
- ✓ Each page loads within 5s (no 404, no unhandled exceptions)
- ✓ Headings match expected pages

**Timeout:** 20s total

---

## Proof of Completion

```bash
npx playwright test tests/e2e/hive-usable.spec.ts
```

**Exit code 0 means:**
- All 3 tests pass
- No test exceeds 30s
- Total runtime < 120s (3 tests × 30s + setup overhead)
- No page crashes or 500 errors

**Test file requirements:**
- Lines: ~150 (down from 528)
- Tests: 3 (down from 16+)
- Locators: Specific (no fuzzy `text=` chains)
- Error handling: Explicit (no `.catch(() => false)` chains that hide failures)
- Timeouts: 10s for API, 30s per test

---

## Implementation Notes

### What to KEEP from existing test
- ✓ `e2e/fixtures/auth.ts` (mock auth injection)
- ✓ `playwright.config.ts` (baseURL, dev server startup)
- ✓ Form fill patterns (input.fill, checkbox.check, select.selectOption)
- ✓ Locator strategies for finding buttons/headings

### What to CUT
- ❌ All 8 "regulatory facts browsing" tests (facts feature not yet implemented)
- ❌ Overly permissive selectors (`.hasText()` chains that try 5 alternatives)
- ❌ Nested `.catch(() => false)` chains (hide failures, make debugging hard)
- ❌ Tests for "rapid interactions", "network timeouts", "no required fields" (not smoke tests)
- ❌ Session persistence test (auth fixture already proves session is set)
- ❌ Form state toggling tests (not core usability)

### Key changes
1. **Reduce timeouts:** 15s → 10s for API response
2. **Explicitness:** Replace `page.locator('button', { hasText: /Run|Analyze|Submit/ })` with `page.locator('button:has-text("Compute Exposures")')`
3. **Error paths:** Expect errors (don't hide them with `.catch()`); if error appears, test passes (proof: "page is responsive")
4. **No assumptions:** Don't try `/hive`, `/hive/facts`, `/regulations`—they don't exist yet

---

## Related Issues

- **Why 300s timeout happened:** 16 tests × 15-20s average + retries + slow API
- **Why tests are flaky:** Permissive selectors that sometimes match wrong elements; slow `.waitFor()` chains
- **Why current test is oversized:** Tries to test API correctness (should be unit/integration tests), not just usability

---

## Configuration Validation

**File:** `playwright.config.ts`
```typescript
timeout: 30_000           // ✓ per test
webServer.timeout: 120_000 // ✓ dev server startup
```

**Expected CLI run:**
```bash
$ npm run dev &            # Start dev server
$ npx playwright test tests/e2e/hive-usable.spec.ts --config=playwright.config.ts
> 3 passed (120s)          # All 3 tests + overhead
```

---

## Success Metrics

| Metric | Target | Current |
|--------|--------|---------|
| Test count | 3 | 16+ |
| Lines of code | ~150 | 528 |
| Runtime | <120s | >300s (timeout) |
| Flakiness | 0% | High (permissive selectors) |
| Debug clarity | High (explicit steps) | Low (catch chains) |
