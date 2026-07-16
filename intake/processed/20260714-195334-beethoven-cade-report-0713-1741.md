PROJECT: beethoven

# Weekly report + ad-hoc 80% email alert for CADE learning progress. Extends the
# existing owner report (runner/owner_report.py) and the email path
# (runner/notify.py, RESEND_API_KEY). Merge gate = runner test suite.

- id: cade-weekly-report-section
  title: Add a CADE learning-progress section to the weekly owner report
  material: no
  model: sonnet
  depends: []
  proof: `python -m pytest runner/tests/ -q` exits 0 (incl. new runner/tests/test_cade_report.py)
  prompt: |
    Extend runner/owner_report.py (the weekly report to Bear) with a CADE section:
    per app + domain, show sample size n, rolling accuracy vs the 80% floor / 90%
    preferred, ECE, current publish TIER (none/conservative/moderate/full), progress
    to the next tier (100 -> 1000 -> 5000), count of drafts awaiting review, and top
    validated theories. Read the per-app CADE ledgers via an INJECTED Supabase client
    (fixtures in tests, no live DB). Add runner/tests/test_cade_report.py asserting the
    section renders tier + progress correctly. Additive; do not change the rest of the
    report.

- id: cade-80pct-email-alert
  title: Ad-hoc email the operator the moment a domain crosses the 80% floor
  material: yes
  model: sonnet
  depends: [cade-weekly-report-section]
  proof: `python -m pytest runner/tests/ -q` exits 0 (incl. new runner/tests/test_cade_alert.py)
  prompt: |
    Add a runner check (runner/cade_alert.py + a scheduled hook) that, between weekly
    reports, watches each domain's rolling accuracy and n, and the FIRST time a domain
    reaches the conservative tier (accuracy >= 80%, ECE <= 0.05, n >= 100) sends Bear an
    immediate email via runner/notify.py (RESEND_API_KEY) — subject like "CADE:
    <domain> hit 80% at conservative tier (n=<n>)" with the numbers + a link to the
    admin review console. Fire ONCE per domain per tier (dedupe/state so it doesn't
    repeat). Also fire on reaching moderate (n>=1000) and full (n>=5000). Test the
    threshold-crossing + dedupe with a fake mailer (no network). Material: sends email.

OPERATOR:
  - Confirm RESEND_API_KEY (or notify.sh) is set so the 80% alert can send; confirm the recipient (Bear's email).
  - Read-only Supabase creds per app for the report/alert to read CADE ledgers.
