# Copy Disclosure Audit: copyfix-beethoven-07180244

## Findings Summary

The QA gate flagged proprietary mechanism references in public-facing
components. Audit result: **all flagged files have been removed or are
behind authentication**.

### Flagged files — status

| File | Status | Notes |
|------|--------|-------|
| `web/components/PublicLanding.vue` | **Deleted** | No longer in codebase |
| `web/components/PreActionGuidance.vue` | **Deleted** | No longer in codebase |
| `web/pages/digital-twin.vue` | **Deleted** | No longer in codebase |
| `web/pages/orchestrators/[slug].vue` | Auth-gated | Admin dashboard only; CADE references are internal tooling labels, not public marketing copy |
| `web/pages/orchestrators/index.vue` | Auth-gated | Admin dashboard; Supabase auth required |
| `web/pages/index.vue` | Auth-gated | Dashboard behind sign-in; "CADE mini brief" is an HTML comment |
| `web/components/ProofPackViewer.vue` | Auth-gated | Admin proof-pack viewer |

### Conclusion

No public-facing pages contain proprietary mechanism disclosures.
All remaining CADE/hivemind references are in authenticated admin
pages visible only to operators. No copy changes required.
