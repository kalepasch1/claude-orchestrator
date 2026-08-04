# Universal Connectors + Zero-Copy Ingest + 1-Click Prod Deploy (Apparently + orchestrator web)

Operator directive 2026-07-30. Three coupled workstreams.

## A. 1-click approve/deploy remediations to the CUSTOMER'S production
Orchestrator web + Apparently both get a deploy-approval surface: an approved
remediation/improvement deploys to the customer's own hosting with one audited click.
- HOSTING CONNECTORS: Vercel, Netlify, Cloudflare Pages/Workers, AWS (Amplify/ECS/Lambda), GCP
  (Cloud Run), Azure (App Service/SWA), Render, Fly.io, Railway, Heroku, DigitalOcean App
  Platform + generic webhook/CI trigger (GitHub Actions/GitLab CI/CircleCI).
- SELF-HOSTED path: guided self-setup — customer registers a deploy endpoint (their own
  webhook/SSH-runner/agent) with a signed handshake; we trigger, they execute; status streams
  back. Anticipate air-gapped: downloadable signed bundle + manifest as the floor.
- Every deploy: preview-before-approve (exact diff/artifact), permissions+constitution gated
  (deploy = HIGH-risk dimension by default), rollback button, full audit chain.

## B. Connectors for EVERYTHING (ingest must be flawless on any stack)
- REPOS: GitHub, GitLab, Bitbucket, Azure DevOps, Gitea/self-hosted git (https+ssh), plain
  git-remote URL.
- DATABASES: Postgres/Supabase, MySQL/Maria, SQLite (upload), MongoDB, SQL Server, BigQuery,
  Snowflake, Redshift — read-only credentials, schema-first introspection.
- EMAIL: Gmail/Google Workspace, Microsoft 365/Outlook, generic IMAP.
- DOCS/FOLDERS: Google Drive, OneDrive/SharePoint, Dropbox, Box, Notion, Confluence, local
  folder upload/sync agent.
- ACCEPTANCE: an integration test PER connector proving real ingest end-to-end (fixture
  accounts/repos), not just OAuth completion. A connector that half-works is marked degraded in
  the UI, never silently green.

## C. ZERO-COPY DEEP INGEST (the cost architecture — critical)
We do NOT mirror customer data into our DB (that cost curve is fatal). Instead:
- QUERY-ON-DEMAND: connectors fetch live when analysis runs; nothing bulk-copied.
- DISTILLED MEMORY ONLY: what persists is the DERIVED layer — embeddings, extracted
  obligations/deadlines/entities, the company_context snapshot, skill/episode summaries, content
  DIGESTS (sha256 + pointer) for freshness detection. Raw bytes stay in the customer's systems;
  our rows are analysis, not archive.
- FRESHNESS: digest-diff per source on a schedule (webhooks where offered) -> re-derive only what
  changed -> the freshness-badge machinery reads this.
- The derived layer feeds: gradients (company_context), hivemind (k>=3 aggregates), the
  newsletter renderer, exam-prep evidence mapping — one distillation, every consumer.
- 50-500X: per-source "memory density" meter shown to the customer (what we know vs. what's
  connected) — the same coverage meter that firms the Hedge & Proceed guide price.

## Guardrails
Read-only scopes everywhere by default; per-source consent + revocation purges the derived rows
(digest-addressed, so purge is complete); no secrets in code (env/vault per app convention);
every connector's failure mode is loud (degraded badge + notification), never silent.
