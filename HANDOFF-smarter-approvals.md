# Handoff — manage orchestrator approvals from Smarter

You (the owner) want to clear decisions from **Smarter** as well as / instead of the cockpit. Because
every app shares the same Supabase, Smarter needs no new backend — it reads and writes the same
`approvals` queue. Single approval is final (no secondary approver).

## Read the queue (one view, already created)
```sql
select * from v_pending_decisions order by (kind='legal') desc, created_at desc;
```
Columns: `id, kind (legal|material|secret|operator), legal_risk_level, radar_tag, app, title, why,
prebrief (plain-English legal brief), draft (exact steps for action items), draft_cmd, executable,
exec_status, created_at`.

Group in the Smarter UI as:
- **Decisions** — `kind in ('legal','material')` → show `prebrief`, Approve / Reject.
- **Action items** — `kind in ('secret','operator')` → show `draft` + `draft_cmd` (+ a Run button if
  `executable=true`), Mark done / Not needed.

## Act on one (single approval = final)
```sql
-- approve / reject / mark-done
update approvals set status='approved', decided_by='smarter', decided_at=now() where id = $1;
update approvals set status='denied',   decided_by='smarter', decided_at=now() where id = $1;
-- one-click run a safe operator step (the runner executes queued rows, re-validating the allowlist)
insert into action_runs (approval_id, cmd, requested_by, status)
  values ($id, (select draft_cmd from approvals where id=$id), 'smarter', 'queued');
update approvals set exec_status='queued' where id=$id;
```

## Push feed (badge / inbox in Smarter)
`notifications` (channel='smarter') gets a row per new decision/action:
```sql
select * from notifications where channel='smarter' and sent=false order by created_at desc;
-- after showing them: update notifications set sent=true, sent_at=now() where id = any($ids);
```

## Notes
- Use the orchestrator Supabase `SUPABASE_URL` + service key (server-side in Smarter only — never ship
  the service key to the browser). For a browser client, go through a small Smarter API route.
- The optional edge function `supabase/functions/approvals-api` (below) wraps list+decide if you'd
  rather not query tables directly.
- Legal cards tagged `legal_risk_level='novel'` are the ones that truly need you; `routine` may be
  auto-cleared by `legal_triage` when `LEGAL_AUTO_APPROVE_ROUTINE=true`.
