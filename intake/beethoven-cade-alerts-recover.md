PROJECT: beethoven
- id: cade-firstpass-email
  title: Email the operator when the first full CADE pass completes (with health report)
  material: yes
  model: sonnet
  depends: []
  proof: `python -m pytest runner/tests/ -q` exits 0 (incl. new runner/tests/test_cade_firstpass.py)
  prompt: |
    Add runner/cade_firstpass.py (+ hook) reading the persisted FullPassReport (injected
    Supabase client). First time report.complete: email Bear via runner/notify.py the health
    report (first result domain/Brier/correct, per-stage status, per-domain accuracy/tier,
    top experts). If stages failed/missing: email a NOT-operational alert + fix directive.
    Fire once; re-alert on regression. Test complete/broken/dedupe with a fake mailer.
- id: cade-weekly-report-section
  title: Add a CADE learning-progress section to the weekly owner report
  material: no
  model: sonnet
  depends: []
  proof: `python -m pytest runner/tests/ -q` exits 0 (incl. new runner/tests/test_cade_report.py)
  prompt: |
    Extend runner/owner_report.py: per app+domain - n, accuracy vs 80%/90%, ECE, tier,
    progress to next tier (100->1000->5000), drafts awaiting review, top validated theories.
    Injected Supabase client; test tier+progress rendering.
- id: cade-80pct-email-alert
  title: Ad-hoc email the operator the moment a domain crosses the 80% floor
  material: yes
  model: sonnet
  depends: [cade-weekly-report-section]
  proof: `python -m pytest runner/tests/ -q` exits 0 (incl. new runner/tests/test_cade_alert.py)
  prompt: |
    Add runner/cade_alert.py (+ hook): first time a domain reaches conservative (acc>=80%,
    ECE<=0.05, n>=100) email Bear immediately via runner/notify.py + console link; also at
    moderate (1000) and full (5000). Once per domain per tier (dedupe). Test crossing+dedupe.
OPERATOR:
  - Confirm RESEND_API_KEY + recipient; read-only Supabase creds per app.
