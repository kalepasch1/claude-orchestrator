# Approval Policy — Routing Reference

## Tier Definitions

| Tier | Scope | Examples |
|------|-------|---------|
| A | Outreach only — no commitment | Negotiation drafts, info requests |
| B | Non-money commitments | Config changes, subscription pauses |
| C | Money movement (signed token) | Fund transfers, purchases, trades |

## State Machine
```
proposed → awaiting_approval → approved → executing → done | failed | expired
```

## Signed Token (Tier C)
HMAC-SHA256 of `{actionId, action, amountUsd, category, userId}` using `AGENT_SIGNING_SECRET`.
Tokens are single-use and verified before execution.

## Digest Ranking
`rankAndBundleDigest()` in `approvalPolicy.js` re-ranks pending approvals by
urgency and value so the most important items surface first in the inbox.
