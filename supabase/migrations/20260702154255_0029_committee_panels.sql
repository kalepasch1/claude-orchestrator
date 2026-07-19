alter table committees add column if not exists seats jsonb;   -- array of expert-seat personas (the panel)
alter table committees add column if not exists chair text;    -- chair who synthesizes consensus

-- the drafted consensus opinion (like a legal opinion memo) per subject per committee
create table if not exists committee_opinions (
  id uuid primary key default gen_random_uuid(),
  subject_type text, subject_id uuid, subject_title text, committee text,
  consensus_verdict text, conviction numeric, rounds integer,
  opinion text, dissent text, created_at timestamptz default now()
);
create index if not exists idx_copin on committee_opinions(subject_type, subject_id);

-- populate each committee with a 3-seat expert panel + a chair (professional archetypes, not individuals)
update committees set chair='Managing Partner', seats='["Veteran securities/regulatory attorney","Consumer-finance & licensing counsel","IP & contracts specialist"]' where name='Legal & Compliance';
update committees set chair='CMO', seats='["Category-defining brand strategist","Performance/growth marketer","PLG & positioning expert"]' where name='Business Development & Marketing';
update committees set chair='CFO', seats='["Unit-economics analyst","SaaS pricing strategist","Capital-efficiency operator"]' where name='Finance & Unit Economics';
update committees set chair='Chief Product Officer', seats='["Jobs-to-be-done researcher","Design/UX craftsman","0-to-1 product builder"]' where name='Product & UX';
update committees set chair='CISO', seats='["Application-security lead","Identity/auth architect","Abuse & fraud specialist"]' where name='Security & Trust';
update committees set chair='Head of Growth', seats='["Experiment-design scientist","Retention/lifecycle expert","Funnel & activation analyst"]' where name='Growth & Experimentation';
update committees set chair='Chief Risk Officer', seats='["Pre-mortem red-teamer","Second-order-effects analyst","Base-rate skeptic"]' where name='Risk & Devil''s Advocate';
update committees set chair='Chief Monetization Officer', seats='["Price-elasticity economist","Packaging/tiering strategist","Willingness-to-pay researcher"]' where name='Pricing & Monetization';
update committees set chair='Head of Competitive Strategy', seats='["Market-teardown analyst","Moat & differentiation strategist","Positioning war-gamer"]' where name='Competitive Intelligence';
update committees set chair='Chief Privacy Officer', seats='["Data-residency & GDPR/CCPA counsel","PII minimization engineer","Consent & governance architect"]' where name='Data & Privacy';
update committees set chair='Head of Partnerships', seats='["Channel/distribution dealmaker","Platform-integration strategist","Partner-leverage vs dependency analyst"]' where name='Partnerships & Alliances';
update committees set chair='Investor-in-Residence', seats='["Metrics & narrative (Series A) partner","Unit-economics diligence lead","Defensibility/TAM analyst"]' where name='Fundraising & Investor';
update committees set chair='VP Customer', seats='["Voice-of-user researcher","Support-signal analyst","Churn-reason interviewer"]' where name='Customer & Voice-of-User';
update committees set chair='Chief Architect', seats='["Scalability/systems engineer","Tech-debt & maintainability lead","Data-model & API design expert"]' where name='Architecture & Scalability';;
