insert into committees (name, mandate, focus) values
 ('Pricing & Monetization','Optimize tiers, packaging, and price elasticity per app — the highest-leverage lever. Push for the pricing/monetization change with the best expected margin x conversion.','pricing'),
 ('Competitive Intelligence','Ground every idea in what rivals are actually doing; flag where we are behind or can leapfrog. Cite the competitive move a proposal answers.','competitive'),
 ('Data & Privacy','Guard PII, data residency, consent, and cross-app data isolation. Ensure capability-sharing never leaks customer data.','privacy'),
 ('Partnerships & Alliances','Evaluate BD/integration deals and channels that unlock distribution or capability. Weigh partner leverage vs. dependency.','partnerships'),
 ('Fundraising & Investor','Frame each move against metrics + narrative an investor would fund: growth, retention, unit economics, defensibility.','investor'),
 ('Customer & Voice-of-User','Represent the real user against internal bias; is this a sharp pain relieved, or a nice-to-have? Cite the user job-to-be-done.','customer'),
 ('Architecture & Scalability','Weigh long-horizon technical debt, scale limits, and maintainability against short-term speed.','architecture')
on conflict (name) do nothing;

-- calibration: track each committee's prediction vs. realized outcome so accurate ones gain weight
alter table committee_reviews add column if not exists outcome numeric;   -- realized result (revenue delta / merged-ok)
create table if not exists committee_calibration (
  committee text primary key, n integer default 0, brier numeric, accuracy numeric,
  weight numeric default 1.0, updated_at timestamptz default now()
);;
