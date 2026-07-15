drop view if exists v_pending_decisions;
create view v_pending_decisions as
select id, kind, legal_risk_level, radar_tag,
       coalesce(project, '-') as app,
       title, why, prebrief, draft, draft_cmd, executable, exec_status, created_at,
       alternatives,                -- [{label, description, risk, reversible, recommended}]
       brief_json,                  -- {question, header, options[], recommended_index}
       decision_type, decision_text
from approvals
where status = 'pending'
  and (kind = any (array['legal','material','secret','operator'])
       or title ~* 'legal|counsel|cftc|dcm|licens|regulat|securities');;
