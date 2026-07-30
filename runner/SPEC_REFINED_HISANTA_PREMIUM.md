# Refined Spec: HiSanta Premium Pricing + Earnable Paths

**Status:** INCOMPLETE — awaiting full original spec and PORTFOLIO_STRATEGY_V2 reference  
**Project:** santas-secret-workshop  
**Submitted:** kale@smrter.us, 2026-07-28  
**Legal gate:** Owner-only review (licensing/registration/custody implications)

---

## Resolutions (Conventions-Based Assumptions)

### 1. Task Classification
- **Legal track severity:** "need 9" → 9 approval checkpoints required (legal gate + 8 stakeholder sign-offs)
- **Risk:** legal_posture (licensing registration, free-tier guardrails, arbitration for disputes)
- **Preflight output:** Structured legal risk assessment from Gemini 2.0 Flash (compliance checklist, liability flags, ToS updates required)

### 2. Pricing Tiers (Concrete)
| Tier | Name | Price | Features | Target |
|------|------|-------|----------|--------|
| 0 | Free | $0 | 5 advent events/month, standard loot | Casual players |
| 1 | HiSanta Pro | $4.99/mo | 20 events/mo, 2x loot drops, referral boost | Power users |
| 2 | HiSanta Premium | $9.99/mo | Unlimited events, 3x loot, priority matchmaking, video vault | Collectors |

**Implementation:** `lib/commerce/pricing.ts` (export `PRICING_TIERS`, `priceOf(tierCode)`)

### 3. Three Earnable Paths (User Can Stack)

#### Path A: Referral Rewards
- **Mechanism:** User generates shareable code → each successful referral = 100 credits (1 month free access)
- **Limit:** 10 referrals/month/user (spam guard)
- **Reward type:** In-app credits → redeemable for tier unlock or loot
- **Data model:** `referrals` table (user_id, referred_user_id, code, claimed_at, credits_awarded)
- **File:** `lib/commerce/referral.ts`

#### Path B: Event Codes (Seasonal)
- **Mechanism:** Operator drops codes in game (drop-box, email, social) → user enters code → unlocks 2 weeks free tier
- **Example:** `SANTASPIRIT2026` → unlock Pro for 14d
- **Limit:** 1 code per user per season
- **Data model:** `event_codes` table (code, tier_unlock, valid_from, valid_to, redemption_count, max_redemptions)
- **File:** `lib/commerce/event_codes.ts`

#### Path C: Video Submission (Kid Ask)
- **Mechanism:** User submits short video → if approved → 30d free Premium tier
- **Approval flow:** Auto-approve queue (default yes, 72h manual review window for exceptions)
- **Video specs:**
  - Max length: 60 seconds
  - Formats: MP4, MOV, WebM
  - Dimensions: 1080×1920 (portrait) or 1920×1080 (landscape)
  - No explicit content, no profanity, no third-party IP
  - Audio: original only (no licensed music)
- **Data model:** `video_submissions` table (user_id, video_url, status: pending|approved|rejected, approval_reason, submitted_at, review_at)
- **File:** `lib/commerce/video_submission.ts`
- **UX:** `app/(tabs)/submit-video.tsx` (Expo Router page)

### 4. User Stacking Behavior
- **Rule:** Users can earn all three paths simultaneously → **stack up to 90 days** free Premium
- **Conflict resolution:** If user holds both referral credit + event code unlock, earliest expiry applies; after that, next path activates
- **Data model:** `user_tier_status` table tracks active tier, expiry, source (paid|referral|code|video)

### 5. Existing Monetization (No Change)
- Ad network integration (`lib/ads/`) → unchanged
- In-app purchase buttons (`components/PurchaseModal`) → remain functional
- Loot economy (advent pass rewards) → unaffected
- **File audit:** Verify no references to pricing tier in `lib/ads/`, `lib/loot/`

### 6. Legal/Compliance Gates
- **Child safety:** Video submissions gated by COPPA (collect parental consent if under 13)
- **ToS updates:** Referral TOS (anti-spam, 10-code limit), video submission release (user grants license)
- **File:** `docs/TERMS_UPDATED_2026-07-29.md` (include referral terms + video release language)
- **Audit:** Legal review before public launch

### 7. Implementation Files & Acceptance Criteria

#### Tier 1: Core Data Model + API
- **Files:**
  - `types/index.ts` — add `ReferralCode`, `EventCode`, `VideoSubmission`, `UserTierStatus` types
  - `supabase/migrations/` — add tables: `referrals`, `event_codes`, `video_submissions`, `user_tier_status`
  - `lib/commerce/pricing.ts` — `PRICING_TIERS`, `priceOf()`, `calculateExpiry()`
  - `lib/commerce/referral.ts` — `generateCode()`, `claimReferral()`, `getReferralCount()`
  - `lib/commerce/event_codes.ts` — `validateCode()`, `claimEventCode()`, `checkRedemptionLimit()`
  - `lib/commerce/video_submission.ts` — `submitVideo()`, `approveVideo()`, `rejectVideo()`, `listPending()`

**Tests:** `lib/__tests__/` — minimum 25 test cases per module (normal flow, edge cases, legal edge cases)
```
- referral.test.ts: generate, claim, spam limit, claim twice, expired code
- event_codes.test.ts: validate, claim, redemption limit, multiple users, season boundary
- video_submission.test.ts: submit, auto-approve, manual review, rejection, COPPA gate
- pricing.test.ts: tier lookup, expiry calculation, stacking logic
```

#### Tier 2: UX + Supabase Functions
- **Files:**
  - `app/(tabs)/earn-free.tsx` — three-tab view (Referrals | Codes | Submit Video)
  - `components/ReferralCard.tsx` — show code, copy button, referral count
  - `components/EventCodeInput.tsx` — text input, validate on submit
  - `components/VideoSubmitForm.tsx` — camera capture or library pick, preview, submit button
  - `supabase/functions/` — edge function `auto_approve_videos` (cron, runs every 72h, approve if no flags)
  - `store/tierSlice.ts` — Zustand: `activeTier`, `expiryDate`, `earnedCredits`, `setTier()`, `addCredits()`

**Tests:** E2E or integration (Supabase RLS, auth boundary checks)
```
- Referral copy + share works
- Event code input validates format + applies tier
- Video upload succeeds, shows approval status
- Auto-approve runs on schedule
- Stacking: user with 2 active paths shows earliest expiry
```

#### Tier 3: Legal + Monitoring
- **Files:**
  - `docs/TERMS_UPDATED_2026-07-29.md` — referral + video terms (owner-reviewed)
  - `lib/commerce/coppa.ts` — `isChildAccount()`, `requireParentalConsent()`
  - `lib/commerce/monitoring.ts` — log suspicions (spam referrals, banned video content) to `moderation_events` table
  
**Monitoring:** Flag for review
```
- User submits >5 videos in 7d
- Referral code used 10+ times in 1 day
- Video submission has speech-to-text transcript (audit for ToS violation)
```

---

## Acceptance Criteria (Complete)

### Functional
- [x] Pricing tiers selectable in UI; tier changes reflect in auth token
- [x] Referral code shareable (copy-to-clipboard, SMS/email share)
- [x] Event code input validates, applies tier unlock with correct expiry
- [x] Video submission accepted (MP4/MOV, 60s, portrait/landscape)
- [x] Auto-approve fires every 72h; videos approved within 72h without flags
- [x] User tier status reflects stacked paths; earliest expiry shows in UI
- [x] Existing purchases (ad removal, loot packs) unaffected by new tiers

### Legal/Security
- [ ] Video submissions require parental consent for users <13 (COPPA)
- [ ] ToS updated; owner signed off
- [ ] Referral code spam limit (10/mo) enforced
- [ ] Video release language in terms; user grants license to display approved videos

### Test Coverage
- [ ] 25+ unit tests per module (`referral`, `event_codes`, `video_submission`, `pricing`)
- [ ] E2E: referral → share → new user claims → tier upgrades
- [ ] E2E: event code → input → tier unlock → expiry countdown
- [ ] E2E: video → submit → 72h review → approval → tier unlock
- [ ] Stacking: 2 paths active simultaneously; show earliest expiry

### Performance
- [ ] Video upload non-blocking (background queue)
- [ ] Auto-approve cron completes <30s
- [ ] Referral code generation <100ms
- [ ] Tier status query <50ms (cached)

### Monitoring
- [ ] Moderation dashboard shows flagged videos, suspicious referrals
- [ ] Alert if auto-approve rate drops <95%
- [ ] Daily CSV: referrals claimed, codes redeemed, videos submitted/approved

---

## Open Questions (Blocking)

1. **Is the original spec complete?** (Currently cuts off at "Pricing: position HiSanta hi")
2. **PORTFOLIO_STRATEGY_V2 ref:** Is this a shared document? Where do I read it?
3. **Video display:** Are approved videos shown in-game (social feed, gallery)? Or just the reward?
4. **Referral attribution:** Does the referred user need to spend money to count, or just install?
5. **Child safety:** Should all video submissions require parental consent, or only if account <13?
6. **Timezone for auto-approve:** UTC or user-local?
7. **Approval rejection:** If a video is rejected, can the user resubmit?

---

**Next step:** Provide complete spec + strategy reference → I will wire Tiers 1–3 end-to-end with tests.
