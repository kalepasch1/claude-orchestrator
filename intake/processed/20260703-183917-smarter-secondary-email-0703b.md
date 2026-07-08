PROJECT: smarter

- id: smarter-secondary-email-address
  title: Add kale@heretomorrow.us as a secondary source feeding the same Smarter account
  material: no
  model: sonnet
  depends: [smarter-email-time-cap]
  proof: npm run build && npm test
  prompt: |
    Support MULTIPLE email addresses feeding ONE Smarter workspace/account, with a per-address
    since-date. Primary kalepasch@gmail.com is time-capped at EMAIL_INGEST_SINCE=2025-10-01. Add
    kale@heretomorrow.us as a SECONDARY source feeding the SAME account / inbox / decision queue,
    but ingesting its FULL mailbox history (no since-cap).
    Implement a per-account since map: env EMAIL_INGEST_SINCE_MAP, JSON like
    {"kale@heretomorrow.us": null, "kalepasch@gmail.com": "2025-10-01"} with fallback to
    EMAIL_INGEST_SINCE; a null/absent value means full history. In server/utils/emailSync.ts resolve
    the since-date per account BEFORE building the Gmail `after:` / Graph `$filter` clause, and OMIT
    the clause entirely when the resolved value is null (full history). Both addresses flow through
    the SAME actionableFilter + 6-agent pipeline into ONE decision queue. Reuse the existing account
    model in server/utils/state.ts / oauth.ts — do not fork the pipeline. Add a unit test that the
    secondary address yields NO `after:` clause while the primary yields `after:2025/10/01`.

OPERATOR:
  - Authorize Gmail OAuth for BOTH kalepasch@gmail.com AND kale@heretomorrow.us (each grants a refresh
    token; they may be separate Google accounts feeding one Smarter workspace). kale@heretomorrow.us
    ingests full history; kalepasch@gmail.com from 2025-10-01.
  - Set EMAIL_INGEST_SINCE_MAP in smarter env (Vercel + runner) once both accounts are connected.
