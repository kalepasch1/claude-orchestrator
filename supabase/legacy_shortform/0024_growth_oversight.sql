-- 0024_growth_oversight.sql
-- Oversight view for the Orchestrator: ties marketing (momentum/budget/spend) to AI token usage
-- (app_operations cost) per app, so marketing spend can dictate token/improvement focus. Idempotent.
create or replace view growth_spend_tokens as
select a.app, a.display_name, a.tier,
  coalesce(m.score,0)      as momentum,
  coalesce(b.allocation,0) as marketing_budget,
  coalesce(b.spend,0)      as marketing_spend,
  coalesce(t.token_cost,0) as token_cost_30d,
  coalesce(t.ops,0)        as ai_ops_30d
from growth_apps a
left join growth_momentum_latest m on m.app = a.app
left join growth_budget b on b.scope='app' and b.key = a.app
left join (
  select app, sum(cost_usd) as token_cost, count(*) as ops
  from app_operations where created_at >= now()-interval '30 days' group by app
) t on t.app = a.app
where a.tier <> 'infra';
