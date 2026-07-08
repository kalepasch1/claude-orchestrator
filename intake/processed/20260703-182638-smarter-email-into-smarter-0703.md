PROJECT: smarter

- id: smarter-email-time-cap
  title: Time-cap Gmail/Graph ingestion to a configurable start date (Oct 2025)
  material: no
  model: sonnet
  depends: []
  proof: npm run build && npm test
  prompt: |
    Extend the EXISTING email sync — do NOT build a new fetcher. In
    server/utils/emailSync.ts the Gmail list call and the Graph message fetch must only
    ingest mail on/after a configurable start date so we never backfill years of history.
    Add env EMAIL_INGEST_SINCE (default "2025-10-01"). For Gmail, append `after:YYYY/MM/DD`
    to the `q` query param of the messages.list call (Gmail wants slashes). For Graph, add a
    `$filter=receivedDateTime ge <ISO>` clause. Parse EMAIL_INGEST_SINCE once, fail-soft to
    the default if unparseable. Keep it backwards-compatible (unset => default). Add a small
    unit test that the Gmail query string contains the `after:` token and the Graph filter
    contains the ISO date. Keep `npm run build` green.

- id: smarter-actionable-filter
  title: Secondary actionable/spam filter — only task/project/action items pass through
  material: no
  model: sonnet
  depends: []
  proof: npm run build && npm test
  prompt: |
    Create server/utils/actionableFilter.ts as a PURE, testable classifier (heuristic floor +
    optional AI enrich when ANTHROPIC_API_KEY is set, same pattern as askRouter.ts /
    obligationExtract.ts). Export `classifyActionable(msg): { keep: boolean; category:
    'task'|'project'|'action'|'non_actionable'|'spam'; score: number; reason: string }`.
    This is a SECOND layer ON TOP OF Google spam — Google already dropped obvious spam; this
    drops the remaining non-actionable flow-through (newsletters, receipts, marketing,
    notifications, social, automated no-reply blasts, FYI-only threads) so ONLY genuine
    task / project / action items reach the Smarter decision queue. Heuristic signals: sender
    patterns (no-reply@, newsletter@, notifications@, marketing domains, list-unsubscribe
    header), subject/body cues (unsubscribe, "view in browser", promo/receipt/order/digest),
    vs actionable cues (question marks addressed to the user, requests/asks, deadlines,
    "can you / please / need / review / sign / approve", direct human sender). Return keep=false
    for spam/non_actionable, keep=true for task/project/action. Add a thorough unit test with
    ~15 labeled fixtures (mix of clear-keep, clear-drop, borderline). No network in the pure path.

- id: smarter-wire-actionable-filter
  title: Wire the actionable filter into intake so non-actionable mail never becomes a decision
  material: no
  model: sonnet
  depends: [smarter-actionable-filter, smarter-email-time-cap]
  proof: npm run build && npm test
  prompt: |
    In the intake/classification pipeline (server/utils/intake.ts + the auto-intake plugin
    server/plugins/auto-intake.ts, and wherever synced messages are turned into asks/decisions
    e.g. oneTapInbox.ts / approvals.ts), run classifyActionable() from actionableFilter.ts on
    each newly-synced message BEFORE it is surfaced as a decision/ask. If keep=false, mark the
    message classified + filtered (store category+reason for audit; do NOT surface it in the
    inbox/decision queue). If keep=true, continue into the existing 6-agent pipeline unchanged.
    Add an env FLAG SMARTER_ACTIONABLE_FILTER (default true) so it can be disabled. Keep an audit
    count (how many filtered, by category) visible in the existing inbox stats if one exists.
    Add a test that a non_actionable message is filtered out and a task message passes through.

OPERATOR:
  - Wire real Gmail OAuth for kalepasch@gmail.com (server/utils/oauth.ts + /api/auth/google are
    currently stubbed per STRATEGY_10X_MOAT.md). Needs a Google Cloud OAuth client
    (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET) and the user to authorize kalepasch@gmail.com so a
    refresh token is stored. Until this is set, ingestion runs against connected/mock accounts only.
  - Set env in smarter (Vercel + runner): EMAIL_INGEST_SINCE=2025-10-01, AUTO_INTAKE_ENABLED=true,
    AUTO_INTAKE_INTERVAL_MINUTES=5, SMARTER_ACTIONABLE_FILTER=true.
