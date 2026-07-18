-- Kale Pasch public-authority editorial program.
-- All artifacts are review-first. This migration deliberately creates no
-- publishing credentials and no automatic external action.

insert into growth_apps (app, display_name, tier, cluster, stage, audience, north_star, monetization, meta)
values (
  'kale-pasch', 'Kale Pasch', 'spearhead', 'authority', 'live',
  'Founders, market participants, legal peers, journalists, and prospective clients',
  'qualified_inquiry', 'professional-services',
  jsonb_build_object('review_first', true, 'editorial_owner', 'kalepasch@gmail.com')
)
on conflict (app) do update set display_name=excluded.display_name, tier=excluded.tier,
  cluster=excluded.cluster, stage=excluded.stage, audience=excluded.audience,
  north_star=excluded.north_star, monetization=excluded.monetization, meta=excluded.meta,
  updated_at=now();

insert into growth_content (app, topic, primary_keyword, status, meta)
values
  ('kale-pasch', 'The regulated-product launch map', 'regulated product launch', 'planned', jsonb_build_object('pillar','product-governance','cadence','quarterly','requires_human_approval',true,'source_policy','primary sources and approved public materials only')),
  ('kale-pasch', 'Event markets, derivatives, and market integrity', 'event markets derivatives market integrity', 'planned', jsonb_build_object('pillar','derivatives-market-structure','cadence','quarterly','requires_human_approval',true,'source_policy','primary sources and approved public materials only')),
  ('kale-pasch', 'Digital assets and financial-product perimeter', 'digital asset product regulation', 'planned', jsonb_build_object('pillar','fintech-digital-assets','cadence','quarterly','requires_human_approval',true,'source_policy','primary sources and approved public materials only')),
  ('kale-pasch', 'Gaming mechanics and the legal design review', 'gaming mechanics legal review', 'planned', jsonb_build_object('pillar','gaming-interactive-products','cadence','quarterly','requires_human_approval',true,'source_policy','primary sources and approved public materials only')),
  ('kale-pasch', 'AI, evidence, and accountable professional judgment', 'AI evidence professional judgment', 'planned', jsonb_build_object('pillar','legal-technology-governance','cadence','quarterly','requires_human_approval',true,'source_policy','primary sources and approved public materials only'))
on conflict (app, primary_keyword) where primary_keyword is not null do update set topic=excluded.topic, meta=excluded.meta, updated_at=now();

insert into growth_content_calendar (app, platform, kind, cadence, per_period, topic_hint, next_due, meta)
values
  ('kale-pasch', 'medium', 'article', 'weekly', 1, 'Source-led field note across the five editorial pillars', now() + interval '7 days', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('kale-pasch', 'newsletter', 'newsletter', 'monthly', 1, 'Pasch Briefing: field note, working framework, and build update', date_trunc('month', now()) + interval '1 month', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('kale-pasch', 'speaking', 'application', 'monthly', 2, 'Curated speaking and press opportunity applications', date_trunc('month', now()) + interval '1 month', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('tomorrow', 'medium', 'article', 'monthly', 1, 'Event-driven risk, bespoke hedging, and market structure', date_trunc('month', now()) + interval '1 month', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('smarter', 'linkedin', 'post', 'weekly', 1, 'Evidence-first AI and accountable legal operations', now() + interval '7 days', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('apparently', 'medium', 'article', 'monthly', 1, 'Compliance-native launch infrastructure', date_trunc('month', now()) + interval '1 month', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('vigil', 'linkedin', 'post', 'weekly', 1, 'Governed intelligence and regulatory evidence', now() + interval '7 days', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('pareto-2080', 'medium', 'article', 'monthly', 1, 'Long-horizon decisions and personal-finance operating systems', date_trunc('month', now()) + interval '1 month', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('racefeed', 'linkedin', 'post', 'weekly', 1, 'Responsible racing and interactive gaming design', now() + interval '7 days', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('hisanta', 'linkedin', 'post', 'weekly', 1, 'Family rituals, kindness, and responsible child-facing product design', now() + interval '7 days', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('sustainable-barks', 'medium', 'article', 'monthly', 1, 'Sustainability claims, hospitality, and pet products', date_trunc('month', now()) + interval '1 month', jsonb_build_object('requires_human_approval',true,'draft_only',true)),
  ('madeus', 'linkedin', 'post', 'weekly', 1, 'Founder operations and agentic execution with human judgment', now() + interval '7 days', jsonb_build_object('requires_human_approval',true,'draft_only',true))
on conflict do nothing;
