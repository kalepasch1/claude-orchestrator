# Approval Digest Batching Implementation

## Overview

This implementation batches approval decision notifications to a single daily digest email instead of sending them individually. Only critical legal decisions (kind=legal with legal_risk_level=novel) send immediately, while all other approvals accumulate and are sent in the daily digest.

## Changes Made

### 1. approval_push.py

**New Function: `_should_send_immediately(approval)`**
- Returns True only for kind=legal with legal_risk_level=novel
- All other approval types return False (will batch to digest)

**Modified: `run(limit=50)`**
- Changed notification `sent` field from always False to conditional:
  - `sent=True` for critical legal decisions (send immediately)
  - `sent=False` for everything else (batch to digest)
- Immediate notify.send() call only executes for critical decisions
- Skips running the notify.send() for batched approvals

### 2. digest.py

**New Function: `_portfolio_summary()`**
- Returns 3-line portfolio health summary:
  1. Portfolio Health: avg score/100 across N projects
  2. Bottlenecks: top 2 at-risk projects
  3. Action items: count of items needing attention

**New Function: `_build_pending_decisions()`**
- Fetches unsent email notifications from the last 24 hours
- Filters by: channel=email, sent=false, created_at >= 24h ago
- Returns list of pending decision/action notifications

**New Function: `_mark_sent(notification_ids)`**
- Updates each notification ID to set sent=True in the database
- Called after digest is successfully sent

**Modified: `build()`**
- Now returns a tuple: (message_string, notification_ids_list)
- Constructs digest with:
  1. Portfolio summary (3 lines) at the top
  2. Pending decisions/actions section (up to 10 items)
  3. Shipped tasks (last 24h)
  4. Items needing attention (inbox)
  5. Month-to-date spend
  6. Proposed next moves

**New Function: `should_run()`**
- Checks if current UTC hour matches DIGEST_HOUR environment variable
- Returns True if now.hour == DIGEST_HOUR
- Default: DIGEST_HOUR=07 (7:00 AM UTC)

**Modified: `send()`**
- Unpacks tuple from build(): (msg, notification_ids)
- Marks all included notifications as sent after digest is sent
- Ensures idempotency: notifications won't appear in multiple digests

### 3. tests/test_approval_digest_batching.py

Complete test suite with 16 test cases covering:

**TestApprovalPushBatching (7 tests)**
- novel_legal_sends_immediately: Confirms sent=True for kind=legal + legal_risk_level=novel
- routine_legal_skipped: Confirms routine legal is skipped entirely
- material_batches: Confirms kind=material has sent=False
- secret_batches: Confirms kind=secret has sent=False
- operator_batches: Confirms kind=operator has sent=False
- legal_with_non_novel_risk_batches: Confirms kind=legal with other risk levels batch
- dedup_prevents_duplicates: Confirms same approval doesn't create multiple notifications

**TestDigestBatching (6 tests)**
- portfolio_summary_3_lines: Confirms exactly 3 lines in portfolio summary
- digest_includes_unsent_notifications: Confirms unsent notifications appear in digest
- digest_marks_sent_after_building: Confirms db.update is called for sent=True
- digest_includes_portfolio_summary_first: Confirms portfolio summary is first section
- digest_includes_shipped_needs_spend: Confirms all required sections are present
- digest_hour_check: Confirms should_run() respects DIGEST_HOUR env var
- digest_hour_default_07: Confirms default DIGEST_HOUR is 07

**TestShouldSendImmediately (5 tests)**
- novel_legal_returns_true: _should_send_immediately returns True only for critical decisions
- routine_legal_returns_false, material_returns_false, secret_returns_false, operator_returns_false

## Configuration

### Environment Variables

```bash
# Digest scheduling (in .env or launchd plist)
DIGEST_HOUR=07                        # UTC hour to send daily digest (default: 07)

# Email notifications (in .env or launchd plist)
APPROVAL_PUSH_EMAIL=you@example.com   # email for notifications (default: kalepasch@gmail.com)
```

Add to `.env.example` for documentation and reference.

## Batching Logic

### Send Immediately (sent=True)
- kind=legal **AND** legal_risk_level=novel
- Executes notify.send() immediately
- Used for urgent legal decisions that need immediate attention

### Batch to Daily Digest (sent=False)
- kind=legal with legal_risk_level != novel
- kind=material
- kind=secret
- kind=operator
- Queued in notifications table with sent=False
- Included in daily digest at DIGEST_HOUR (default 07:00 UTC)
- Marked sent=True after digest is sent

## Database Schema

### notifications table (required fields)

```
id              uuid primary key
approval_id     uuid (foreign key to approvals.id)
channel         text ('email' or 'smarter')
kind            text ('decision' or 'action')
title           text (notification title)
body            text (notification body, 600 chars max)
audience        text (email address)
sent            boolean (default: false)
created_at      timestamp (auto, created_at.desc for ordering)
```

## Testing

Run the complete test suite:

```bash
python runner/tests/test_approval_digest_batching.py
```

Or with unittest:

```bash
python -m unittest runner.tests.test_approval_digest_batching -v
```

Tests use a MockDB that simulates database behavior without hitting Supabase.

## Example Digest Output

```
*Portfolio Health*: 82.5/100 across 5 projects
Bottlenecks: api, web
Action items: 3 need your attention

*Pending Decisions & Actions*
  • IP agreement review: [proj] Third-party license agreement terms...
  • Pricing model change: [api] Introduce tiered pricing structure...
  • Deploy API: [api] New service version deployment...
  ... and 2 more decisions pending

*Shipped (24h)*: feature-x, bugfix-y
*Needs you*: Deploy blocked: waiting for approval; Bug critical: production issue
*Spend MTD*: api $250.50, web $125.00
*Proposed next*: Refactor auth layer; Add analytics integration
```

## Integration

### Scheduler Configuration

**approval_push.py:**
- Schedule: Every 2-5 minutes
- Purpose: Create notifications for new pending approvals
- Output: Updates notifications table with pending decisions/actions

**digest.py:**
- Schedule: Daily at DIGEST_HOUR (default 07:00 UTC)
- Purpose: Send aggregated digest of pending decisions from last 24h
- Output: Email/Slack message via notify.sh, updates sent=True on notifications

### Workflow

1. New pending approval created → approval_push.py finds it
2. approval_push.py checks `_should_send_immediately()`
   - If critical legal: insert notification (sent=True), call notify.send() immediately
   - Otherwise: insert notification (sent=False), skip notify.send()
3. Non-critical approvals accumulate in notifications table
4. Daily at DIGEST_HOUR, digest.py runs:
   - Fetches unsent notifications from last 24h
   - Builds digest message with portfolio summary + pending decisions
   - Sends via notify.sh
   - Marks all included notifications as sent=True
5. Same approval never appears in multiple digests (idempotent)

## Benefits

1. **Reduced Email Noise**: Non-critical decisions don't spam individual emails
2. **Executive Summary**: 3-line portfolio health context at top
3. **Time-Boxed Review**: All pending decisions reviewed together in daily digest
4. **Critical Path Honored**: Urgent legal decisions still get immediate attention
5. **Idempotent**: Each notification sent exactly once
6. **Audit Trail**: sent=true status tracks which decisions were communicated
