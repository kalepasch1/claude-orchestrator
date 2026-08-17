# REFINED SPECIFICATION: Decision-Budget Linter Integration with Trust Dial

## Executive Summary
The decision-budget linter enforces a **5/95 disclosure doctrine** where essential controls are shown up-front and advanced options are hidden behind disclosure components. The linter validates that each page surface respects its declared budget, with strict enforcement for high-stakes surfaces (war-room, matter-detail, approval flow) regardless of the trust dial setting.

## File Scope (Exact Paths)

### Primary Implementation File
- **`tomorrow/scripts/lint-decision-budgets.mjs`** (Node.js; static analysis, no runtime required)
  - Scans all Vue pages under `tomorrow/pages/`
  - Counts discretionary user controls visible up-front (disclosure-aware)
  - Exits code 0 (pass) or 1 (fail) based on declared-surface violations

### Configuration/Reference Files (Read-Only; Consumed by Lint Script)
- **`tomorrow/server/utils/governance.ts`** — Trust dial configuration (TrustTier enum, budgetMultiplier)
- **`tomorrow/shared/contracts/decisionBudget.ts`** — Shared contract types
- **`tomorrow/server/utils/ux/decisionBudget.ts`** — Canonical decision-counting logic (unit tests keep it in sync)

### Test Files (Verify Lint Correctness)
- **`tomorrow/server/utils/ux/__tests__/decisionBudget.test.ts`** — Server-side budget validation tests
- **CI script**: `npm run lint:budgets` (if defined in package.json)

---

## Ambiguity Resolutions

### 1. **The 5% Value: UI Disclosure Threshold**
**Resolved:** The "5%" refers to the **co_pilot trust tier's 5/95 doctrine**, not a computational budget percentage.

**Concrete Definition:**
- In **co_pilot mode** (the default and strictest practical tier), only the 5% of controls deemed *essential* are shown up-front on a page.
- The remaining 95% of controls are *hidden by default* behind disclosure components (e.g., `<UCollapsible>`, `<UAccordion>`, `<details>`).
- The **budget multiplier** in `server/utils/governance.ts` is `1.0` for co_pilot, meaning: `effectiveBudget(baseBudget) = baseBudget * 1.0`.
- Higher trust tiers (counsel_only = 3.0x, auto_pilot = 0.5x) adjust the visible control count, but strict-enforcement surfaces ignore this multiplier.

**Where it appears in code:**
- `TRUST_DIAL.co_pilot.label`: "Co-Pilot — 5/95 doctrine (5% essential, 95% disclosed)"
- `TRUST_TIERS['co_pilot'].budgetMultiplier`: 1.0

---

### 2. **"Enforce Strict Decision Budgets": Validation Rules**
**Resolved:** Strict enforcement applies to **declared surfaces in high-stakes contexts**, not all surfaces.

**Concrete Validation Rules:**

1. **Declared-Surface Violations** (fail CI)
   - **Scope:** Pages with explicit entries in `DECISION_BUDGETS` dict (e.g., `app/cockpit: 1`, `firm/war-room: 6`)
   - **Check:** If `controlCount > budget`, the lint **fails the build** (exit code 1)
   - **Example:** `app/cockpit` has a budget of 1 control up-front. Two controls = violation.

2. **Strict-Enforcement Surfaces** (always fail CI, even if undeclared)
   - **Scope:** Pages listed in `STRICT_ENFORCEMENT` set:
     - `firm/war-room`
     - `firm/negotiations/war-room`
     - `firm/matter-detail`
     - `app/now/approve`
   - **Check:** These surfaces IGNORE the trust-dial multiplier. They are enforced at their base budget regardless of tier.
   - **Rationale:** High-stakes decisions (approvals, negotiations, matter detail) are cognitively dangerous when overloaded. No autonomy-dial leniency.

3. **Undeclared Surfaces** (advisory only)
   - **Scope:** Pages not in `DECISION_BUDGETS` and not strict-enforcement
   - **Check:** If `controlCount > DEFAULT_BUDGET (2)`, report as advisory (does NOT fail the build)
   - **Rationale:** Low-risk surfaces; guidance for future tightening.

**Exit Behavior:**
- **Exit code 0 (pass):** No declared-surface violations and no strict-enforcement violations.
- **Exit code 1 (fail):** One or more declared or strict-enforcement violations exist.

---

### 3. **Trust Dial Influence on Linting: Gate, Not Modifier**
**Resolved:** Trust dial is a **gate that determines the active baseline tier**, not a dynamic input to the lint script.

**Concrete Behavior:**

1. **What the lint does:**
   - Reads `ACTIVE_TIER` constant (currently hardcoded to `'co_pilot'`)
   - Uses `TRUST_TIERS[ACTIVE_TIER].budgetMultiplier` to compute the effective budget for *non-strict surfaces*
   - Logs which tier is active: `"trust tier: Co-Pilot (5/95)"`

2. **The three trust tiers and their effect:**
   - **counsel_only** (multiplier 3.0)
     - Stricter linting: base budgets are reduced by 1/3
     - More controls are hidden behind disclosure
     - Use case: High governance/compliance environments
   - **co_pilot** (multiplier 1.0, DEFAULT)
     - Baseline enforcement: budgets are as declared
     - Recommended for most teams
   - **auto_pilot** (multiplier 0.5)
     - Lenient linting: base budgets are doubled
     - Fewer controls are hidden (more automation)
     - Use case: Heavily instrumented teams with strong guardrails

3. **How to change tiers:**
   - Modify the `ACTIVE_TIER` constant in `lint-decision-budgets.mjs` (line 39)
   - OR read `DEFAULT_TRUST_TIER` from `server/utils/governance.ts` at runtime (currently hardcoded instead)
   - Strict-enforcement surfaces are NOT affected by this change

**NOT inputs to the lint script:** You cannot pass `--trust=counsel_only` on the CLI. The tier is baked into the script at build time (or can be made env-var configurable in a future version).

---

### 4. **Disclosure Mechanism: Strict-Enforcement Definition in Code**
**Resolved:** The "disclosure mechanism" is the set of component tags that hide controls *from the decision count*.

**Concrete Implementation:**

The linter strips (ignores) any controls nested inside these disclosure components:
```javascript
const DISCLOSURE_TAGS = [
  'UCollapsible',   // Nuxt UI; hides content until clicked
  'UAccordion',     // Nuxt UI; accordion panels
  'details',        // Native HTML; <details><summary>...</summary>...</details>
  'MoreControls',   // Custom; typically a button + modal or popover
  'AdvancedControls', // Custom; advanced options panel
  'DisclosurePanel', // Custom; generic disclosure
  'Teleport',       // Vue; portals (used for modals, popovers)
]
```

**How controls are counted:**
1. Read the Vue file source
2. Strip all disclosure tags and their content: `stripDisclosed(src)`
3. Count remaining control patterns (inputs, selects, toggles, ranges, etc.)
4. Exclude lines marked `<!-- budget:ignore -->`

**Example (5/95 compliant cockpit):**
```vue
<template>
  <OutcomePanel :released="released" />            <!-- Status; not a control -->
  <UToggle v-model="autonomyOn" label="Recommended" /> <!-- The 5%: 1 decision -->
  <UCollapsible title="More controls">
    <!-- These 95% are hidden and don't count toward budget -->
    <UInput v-model="cap" />
    <USelect v-model="tenor" />
    <URange v-model="risk" />
  </UCollapsible>
</template>
```
- **Control count:** 1 (only the toggle is visible up-front)
- **Budget for `app/cockpit`:** 1
- **Result:** ✓ Pass

---

### 5. **Page References: Route Slugs, Not File Paths**
**Resolved:** "war-room", "matter-detail", "now/approve" are **surface IDs** (derived from Vue page paths), not raw file paths or component names.

**Surface ID Derivation:**

The lint script computes the surface ID from the file path using `surfaceId()`:
```javascript
function surfaceId(absPath) {
  // Example: /app/pages/firm/negotiations/[id]/war-room.vue
  // 1. Get relative path from pages/ dir: firm/negotiations/[id]/war-room.vue
  // 2. Remove .vue extension: firm/negotiations/[id]/war-room
  // 3. Drop /[param] segments: firm/negotiations/war-room
  // 4. Drop /index suffix: (no change here)
  // Result: firm/negotiations/war-room
  let rel = relative(PAGES, absPath).replace(/\\/g, '/').replace(/\.vue$/, '')
  rel = rel.replace(/\/index$/, '').replace(/\/\[[^\]]+\]/g, '')
  return rel
}
```

**Mapping (Exact Surface IDs in STRICT_ENFORCEMENT):**
| Vue File Path | Surface ID | In Strict Enforcement? |
|---|---|---|
| `pages/firm/war-room.vue` | `firm/war-room` | ✓ Yes |
| `pages/firm/negotiations/[id]/war-room.vue` | `firm/negotiations/war-room` | ✓ Yes |
| `pages/firm/matter-detail.vue` | `firm/matter-detail` | ✓ Yes |
| `pages/app/now/approve.vue` | `app/now/approve` | ✓ Yes |

These surface IDs MUST match exactly the entries in the `STRICT_ENFORCEMENT` set in the lint script.

---

## Explicit Acceptance Criteria

### Criterion 1: Lint Runs Without Errors
**Input:** Run `node tomorrow/scripts/lint-decision-budgets.mjs`  
**Expected Output:**
```
Decision-budget lint: NNN surfaces scanned (trust tier: Co-Pilot (5/95)).
  M DECLARED-surface violations (these fail CI).
  K strict-enforcement violations.
  P undeclared surfaces over the default budget of 2 (advisory).

[If M > 0 or K > 0:]
Declared-surface violations:
  ✗ <surface-id>  <count> controls / budget <budget>  (over by <overBy>)
  ...
```
**Exit Code:** 0 if `M == 0 && K == 0`; else 1  
**Acceptance:** Script runs deterministically; output is parseable.

---

### Criterion 2: Declared-Surface Budgets Are Enforced
**Setup:** Add a second `<UToggle>` to `pages/app/cockpit.vue` (which has a budget of 1)  
**Run:** `node tomorrow/scripts/lint-decision-budgets.mjs`  
**Expected:**
```
  1 DECLARED-surface violations (these fail CI).
  ...
Declared-surface violations:
  ✗ app/cockpit  2 controls / budget 1  (over by 1)

(strict mode — failing the build if declared surfaces have violations)
Exit code: 1
```
**Acceptance:** The lint fails the build when a declared surface exceeds its budget.

---

### Criterion 3: Strict-Enforcement Surfaces Bypass Trust Multiplier
**Setup:** Temporarily change `ACTIVE_TIER` to `'auto_pilot'` (multiplier 0.5, which would double budgets)  
**Prediction:**
- For `app/cockpit` (not strict): effective budget becomes `1 * 0.5 = 0.5`, rounded to max(1, ...) = 1. Still tight.
- For `firm/war-room` (strict): budget stays 6 (no multiplier applied).

**Run:** Add 7 controls to `pages/firm/matter-detail.vue` (strict, base budget 5)  
**Expected:** The lint still **fails**, reporting:
```
  1 strict-enforcement violations.
  ✗ firm/matter-detail  7 controls / budget 5  (over by 2) [STRICT]
```
**Acceptance:** Strict surfaces are not leniency-dialed by the trust tier.

---

### Criterion 4: Disclosed Controls Don't Count
**Setup:** Create a test page with 5 controls (2 visible, 3 in a `<UCollapsible>`)  
**Code:**
```vue
<template>
  <UToggle v-model="a" /> <!-- visible: count = 1 -->
  <UInput v-model="b" />   <!-- visible: count = 2 -->
  <UCollapsible>
    <UToggle v-model="x" /> <!-- disclosed: not counted -->
    <UInput v-model="y" />  <!-- disclosed: not counted -->
    <USelect v-model="z" /> <!-- disclosed: not counted -->
  </UCollapsible>
</template>
```
**Budget for this surface (undeclared):** DEFAULT_BUDGET = 2  
**Run:** Lint script  
**Expected:** No violation (2 visible <= 2 budget)  
**Acceptance:** Only up-front controls count; disclosure hides complexity.

---

### Criterion 5: `budget:ignore` Comments Exclude Individual Controls
**Setup:** Add a debug input marked `<!-- budget:ignore -->`  
**Code:**
```vue
<template>
  <UInput v-model="important" />  <!-- count this -->
  <UInput v-model="debug" /> <!-- budget:ignore diagnostic -->
</template>
```
**Expected Control Count:** 1 (the second is excluded by the comment)  
**Acceptance:** The `budget:ignore` marker is respected.

---

### Criterion 6: Output Format and Logging
**Run:** `node tomorrow/scripts/lint-decision-budgets.mjs --all --top=5`  
**Expected Output:**
- Line 1: Summary line with surface count and active tier
- Lines 2-4: Violation summary (counts of declared, strict, undeclared)
- Lines 5+: Detailed violations (if any) or all surfaces (if `--all` given, limited to `--top=N`)
- Final line: Pass/fail statement and exit code

**Flags:**
- `--all`: Print every surface (not just violations), sorted by control count descending
- `--top=N`: Limit output to top N surfaces (default: Infinity)

**Acceptance:** CLI flags work as documented; output is suitable for CI logs and debugging.

---

## Trust Tier Configuration (Future Enhancement)

### Recommended: Make ACTIVE_TIER Environment-Configurable
**Current State:** Hardcoded `const ACTIVE_TIER = 'co_pilot'` (line 39)  
**Recommended Future:**
```javascript
const ACTIVE_TIER = process.env.ORCH_DECISION_TIER || 'co_pilot'
```
**Rationale:** Follows the project convention of `ORCH_`-prefixed env vars for fleet-wide config. Allows teams to fleet-push a stricter tier (e.g., counsel_only) without modifying code.

**For Now:** Document that changing the tier requires editing the lint script and re-running CI.

---

## Integration Checklist

- [ ] **Lint script exists and runs:** `tomorrow/scripts/lint-decision-budgets.mjs` ✓
- [ ] **Trust dial config loaded:** `server/utils/governance.ts` defines TRUST_DIAL and STRICT_ENFORCEMENT_SURFACES ✓
- [ ] **Surface budgets declared:** `DECISION_BUDGETS` dict includes all high-stakes surfaces ✓
- [ ] **Disclosure tags recognized:** `DISCLOSURE_TAGS` covers common UI patterns (UCollapsible, details, etc.) ✓
- [ ] **Control patterns match:** `DECISION_PATTERNS` regex array recognizes inputs, selects, toggles, etc. ✓
- [ ] **Test coverage:** `server/utils/ux/__tests__/decisionBudget.test.ts` validates end-to-end logic ✓
- [ ] **Build integration:** CI runs the lint on every build (if `npm run lint:budgets` is hooked in package.json)
- [ ] **Documentation:** This spec explains what each constant means and why strict surfaces exist ✓

---

## Failure Modes & Debugging

### Lint Fails with "NN declared-surface violations"
**Check:**
1. Run `node scripts/lint-decision-budgets.mjs` (from tomorrow/ root)
2. Identify the surface by name (e.g., `firm/matter-detail`)
3. Open the corresponding Vue file and count visible controls (disclosure-aware)
4. Compare against the budget in `DECISION_BUDGETS`
5. Move excess controls into a disclosure component or remove them

### New Page Added; Lint Reports it as "advisory" but Should Fail
**Fix:** Add the surface ID to `DECISION_BUDGETS` with an explicit budget. Once declared, it becomes part of strict enforcement.

### Trust Tier Changed; Budgets Relaxed Unexpectedly
**Check:** 
1. Confirm `ACTIVE_TIER` is set correctly
2. Remember: **Strict-enforcement surfaces ignore the tier multiplier**
3. Non-strict surfaces will relax (or tighten) based on multiplier; this is intentional

---

## Summary of Resolutions

| Ambiguity | Resolution | Source |
|---|---|---|
| **5% value** | UI disclosure threshold; essential controls shown up-front | `TRUST_DIAL.co_pilot.label` |
| **"Enforce strict budgets"** | Validate declared surfaces + high-stakes surfaces against their budget | `DECISION_BUDGETS`, `STRICT_ENFORCEMENT` |
| **Trust dial influence** | Gate that selects the baseline tier; non-strict surfaces scale by multiplier; strict surfaces never scale | `ACTIVE_TIER`, `TRUST_TIERS[tier].budgetMultiplier` |
| **"Disclosure mechanism"** | Controls nested in `DISCLOSURE_TAGS` are excluded from the count | `stripDisclosed()`, `DISCLOSURE_TAGS` |
| **Page references** | Surface IDs derived from Vue paths (drop `/[param]`, `/index`, `.vue`) | `surfaceId()` function |

---

## Commit Ready?

The implementation is **complete and passing**. This spec clarifies the original ambiguous task description. To commit this clarity:

```bash
cd /Users/kpasch/Documents/tomorrow/tomorrow
git add scripts/lint-decision-budgets.mjs server/utils/governance.ts
git commit -m "docs(decision-budget-lint): clarify 5/95 doctrine and strict-enforcement surfaces

This commit documents the refined spec for the decision-budget linter:
- Trust dial sets the baseline tier (co_pilot default); budgets scale by multiplier.
- Strict-enforcement surfaces (war-room, matter-detail, now/approve) always enforce
  their base budget regardless of trust tier.
- The 5% refers to essential controls shown up-front; 95% are disclosed.
- Disclosure components (UCollapsible, details, MoreControls) hide controls from the count.

Exit code 0 when declared and strict surfaces are within budget; else 1.
Run: node scripts/lint-decision-budgets.mjs [--all] [--top=N]

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>"
```

---
