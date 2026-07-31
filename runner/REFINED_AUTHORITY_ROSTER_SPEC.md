# Authority Roster Seed Dataset — Refined Specification

## Executive Summary
Create a curated bootstrap dataset of **50–100 historical and contemporary authorities** in economics, investment, risk management, and central banking. Serve as a seed data source for Tomorrow's advisory context layer, enabling enrichment of risk profiles and narrative authority citations.

---

## Ambiguity Resolutions

### 1. **"Laureate Economist" Definition**
**Decision: Nobel Prize in Economic Sciences (1969–present) + Fields Medal recipients with mathematical economics focus.**

- **Rationale:** Nobel Prize is the objective, globally recognized standard. Fields Medal inclusion captures theoretical economists whose work underpins modern risk and portfolio theory.
- **Scope:** Include living and deceased laureates. Do not expand to other honors (Bates Medal, etc.) to avoid subjective scope creep.
- **Cutoff:** All Nobel laureates 1969–2026; deceased laureates from 2000+ to ensure historical relevance.

### 2. **"Great Investors/Risk Managers/Central Bankers" Metrics**
**Decision: Three-tier inclusion criteria (meet any one tier):**

| Tier | Criteria | Example |
|------|----------|---------|
| **Academic/Policy Impact** | Tenure at top-20 global university OR direct policy influence (e.g., Federal Reserve chair, World Bank chief economist) | Paul Volcker, Janet Yellen |
| **Market/Business Impact** | >$10B AUM managed, or founding/leading a major financial institution, or transformational risk management innovation adopted industry-wide | Ray Dalio, John Bogle |
| **Intellectual Impact** | 5+ widely-cited publications (>1000 Google Scholar citations) in risk/finance, or authored framework adopted in regulation/practice | Nassim Taleb, Daniel Kahneman |

- **Rationale:** Balances academic rigor, practical influence, and thought leadership. Avoids chasing social media fame.
- **Scope:** Include deceased figures (1960+) and living figures. Preference for 20th century figures + select contemporary leaders to maintain historical grounding.

### 3. **Data Source**
**Decision: Tiered sources with fallback hierarchy:**

1. **Primary:** Wikipedia curated lists (Nobel Prize Economics, list of hedge fund managers, list of central bankers) + cross-reference with IDEAS/RePEc
2. **Secondary:** Academic sources (economics department websites at Stanford, MIT, Chicago) for contemporary figures
3. **Initial Release:** Manual curation from tier 1+2. Bootstrap ~80 entries.
4. **Future Path:** Link to RESTful lookup (e.g., IDEAS API) for on-demand enrichment; store only `seed_id` + `source` in JSON.

- **Rationale:** Wikipedia provides verifiability and community maintenance. IDEAS/RePEc is authoritative for academic economists.

### 4. **JSON Schema & Field Definitions**
**Decision: Minimal viable schema with required + optional fields:**

```typescript
interface Authority {
  // Required
  id: string;                    // UUID or slug: "nobel-paulkrugman-2008"
  name: string;                  // Full name: "Paul Krugman"
  role: "economist" | "investor" | "risk_manager" | "central_banker"; // Exactly one
  
  // Credential (at least one required)
  nobel_prize_year?: number;     // 2008 if laureate
  nobel_prize_field?: string;    // "Economic Sciences"
  fields_medal_year?: number;    // If applicable
  institution?: string;          // Current/primary: "MIT"
  aum_billions?: number;         // Assets under management (investors only)
  
  // Context
  birth_year: number;            // 1944
  death_year?: number;           // Omit if living
  country_of_origin: string;     // "United States"
  primary_field: string;         // "Macroeconomics", "Asset Management", "Monetary Policy"
  
  // Summary (for display/matching)
  summary: string;               // 1–2 sentences: "Nobel laureate in economic sciences (2008). Known for new trade theory and analysis of city centers."
  
  // Source & versioning
  source: "wikipedia" | "academic" | "manually_curated";
  source_url?: string;           // Link to verification source
  added_date: string;            // ISO 8601: "2026-07-30"
  verified_by?: string;          // Curator name or "automated"
}
```

**Example entries:**

```json
[
  {
    "id": "nobel-paulkrugman-2008",
    "name": "Paul Krugman",
    "role": "economist",
    "nobel_prize_year": 2008,
    "nobel_prize_field": "Economic Sciences",
    "institution": "MIT",
    "birth_year": 1953,
    "country_of_origin": "United States",
    "primary_field": "International Economics",
    "summary": "2008 Nobel laureate in Economic Sciences. Pioneered new trade theory; influential critic of macro policy during 2008 crisis.",
    "source": "wikipedia",
    "source_url": "https://en.wikipedia.org/wiki/Paul_Krugman",
    "added_date": "2026-07-30",
    "verified_by": "automated"
  },
  {
    "id": "fed-paulvolcker-chair",
    "name": "Paul Volcker",
    "role": "central_banker",
    "institution": "Federal Reserve",
    "birth_year": 1927,
    "death_year": 2019,
    "country_of_origin": "United States",
    "primary_field": "Monetary Policy",
    "summary": "Former Federal Reserve chairman (1979–1987). Architect of disinflation policy in early 1980s; shaped modern central banking doctrine.",
    "source": "wikipedia",
    "source_url": "https://en.wikipedia.org/wiki/Paul_Volcker",
    "added_date": "2026-07-30",
    "verified_by": "automated"
  },
  {
    "id": "investor-raydalio-bridgewater",
    "name": "Ray Dalio",
    "role": "investor",
    "aum_billions": 140,
    "institution": "Bridgewater Associates",
    "birth_year": 1949,
    "country_of_origin": "United States",
    "primary_field": "Systematic Investment & Risk Parity",
    "summary": "Founder of Bridgewater Associates ($140B AUM). Developed principles-based investing and risk parity framework adopted across industry.",
    "source": "wikipedia",
    "source_url": "https://en.wikipedia.org/wiki/Ray_Dalio",
    "added_date": "2026-07-30",
    "verified_by": "manually_curated"
  }
]
```

### 5. **Scope & Integration Context**
**Decision: Use case is *advisory context enrichment* for Tomorrow's risk narratives.**

- **Consumer:** `server/api/risk/enrich.ts` (or similar) will optionally lookup an authority by name/role to attach credibility signals ("Endorsed by Nassim Taleb's fragility principle") or historical precedent ("Paul Volcker faced similar inflationary shock in 1981").
- **Why these roles together:** All four roles (economists, investors, risk managers, central bankers) are decision-makers and thought leaders in the risk/finance domain. They represent the "intellectual credibility layer" above raw market data.
- **Not a trade directory:** This is *not* a list of available advisors to hire. It is historical/academic reference data for enriching risk analysis narratives.

### 6. **Dataset Type & Maintenance**
**Decision: Initial seed dataset; maintained via manual curation + automated Wikipedia/IDEAS polling.**

- **Initial Release:** 50–100 curated entries (v1.0)
- **Versioning:** Store in `data/authorities/roster_v1.0.json`. Update path goes to `v1.1`, `v2.0` if schema changes.
- **Update Cadence:** No automatic refresh in v1. v2 will add async polling (monthly) for Nobel Prize winners and deaths.
- **Change Control:** All updates require a manual PR and code review. No silent mutations.

---

## Acceptance Criteria

### Data Completeness
- [ ] **Roster size:** 50–100 entries (minimum 50, target 80)
- [ ] **Role distribution:** At least 15 economists, 10 investors, 8 risk managers, 7 central bankers (may overlap roles)
- [ ] **Field validation:** No missing required fields (`id`, `name`, `role`, `birth_year`, `country_of_origin`, `primary_field`, `summary`, `source`, `added_date`)
- [ ] **No duplicates:** Verified by unique `id` and unique `name` (case-insensitive)

### Schema & Format
- [ ] **Valid JSON:** Output passes `jq` validation with no syntax errors
- [ ] **Type conformance:** All role values match enum; all dates are ISO 8601 or YYYY integers; AUM is numeric (billions)
- [ ] **Source attribution:** Every entry has `source_url` OR manual curation note; Wikipedia entries link to en.wikipedia.org
- [ ] **Optional fields only when applicable:** `nobel_prize_year` present iff Nobel laureate; `death_year` present iff deceased; `aum_billions` present iff investor

### Accuracy & Verification
- [ ] **Manual spot-check:** 10 randomly selected entries verified against Wikipedia/academic sources (no hallucinations)
- [ ] **Nobel Prize cross-check:** All claimed Nobel laureates in 1969–2026 roster appear in official Nobel Prize database
- [ ] **Consistency:** Same person never appears twice (e.g., "Paul Krugman" only once, even if economist *and* public intellectual)

### Testing & Integration
- [ ] **Test file created:** `tests/data/authorities.spec.ts` with:
  - Schema validation (Zod or TypeScript interface check)
  - 5 example test cases (parse, validate, query by role)
  - Duplicate ID check
  - Date format validation
  - Required field checks
- [ ] **No regressions:** Existing tests pass (no changes to `server/` or `app/` without approval)

---

## File Paths & Deliverables

| Path | Purpose | Format |
|------|---------|--------|
| `data/authorities/roster_v1.0.json` | Main seed dataset (80 entries) | Valid JSON array of Authority objects |
| `data/authorities/schema.ts` | TypeScript type definitions + Zod validator | Zod schema with `.parse()`, `.safeParse()`, `.strict()` |
| `data/authorities/sources.md` | Curation notes & sourcing methodology | Markdown with per-role sourcing rationale & examples |
| `tests/data/authorities.spec.ts` | Unit tests: schema validation, completeness, accuracy | Jest/Vitest test suite (20+ cases) |
| `data/authorities/README.md` | Consumer guide: how to query, integrate, update | API examples, versioning policy, maintenance SLA |

---

## Implementation Roadmap

### Phase 1: Curation & Validation (7–10 days)
1. Collect raw list from Wikipedia Nobel Prize, central bank leadership, investor databases (manual or light scraping)
2. Apply inclusion tiers (economist, investor, risk manager, central banker)
3. Deduplicate and build ~80-entry roster
4. Manually verify 10 spot-checks against sources
5. Export as JSON, validate schema

### Phase 2: Schema & Integration (3–5 days)
1. Define Zod schema in `data/authorities/schema.ts`
2. Write 20+ test cases (validation, duplication, date formats, required fields)
3. Create `server/api/risk/enrich.ts` stub (optional lookup function)
4. Document consumer API in `data/authorities/README.md`

### Phase 3: QA & Merge (2–3 days)
1. Code review: schema design, test coverage, sourcing methodology
2. Run full test suite (no regressions)
3. Merge to `orchestrator/dev`, auto-promote to `main` after batch tests pass

---

## Scope Boundaries (NOT Included in v1)

- ❌ Real-time data sync (Wikipedia polling, IDEAS API integration) — v2 feature
- ❌ Hiring/advisory matching — out of scope; data is reference-only
- ❌ Alternative credentials (Bates Medal, peer recognition surveys) — too subjective
- ❌ Social media metrics (followers, citations velocity) — too volatile
- ❌ Contact information or availability status — privacy & maintenance burden

---

## Success Metrics

- ✅ 80+ curated entries, no duplicates, all fields valid
- ✅ 100% test pass rate (schema validation, spot-checks)
- ✅ Zero manual follow-up questions during code review
- ✅ Consumer API (`server/api/risk/enrich.ts`) successfully integrates and runs a test lookup query
- ✅ Merged to production branch within 10 calendar days

---

## Rationale Summary

This spec transforms a vague ask ("list of every laureate economist and great investors") into a **bounded, verifiable, integrated data resource**:

1. **Objective definitions** (Nobel Prize, institutional tenure, quantifiable metrics) replace subjective "great"
2. **Schema-first design** enables type-safe consumers and future API integration
3. **50–100 entry cap** balances comprehensiveness with curation effort
4. **Explicit file paths** clarify where output lives in the project
5. **Acceptance criteria** make "done" unambiguous
6. **Test-driven** ensures accuracy and prevents silent data rot
7. **Tomorrow integration context** explains why this roster exists (advisory enrichment, not hiring)

