-- Include every Sustainable Barks registration surface in CRM ownership and sequencing.
begin;

insert into growth_crm_ownership_rules(app, lead_type, owner_id, owner_label, sla_hours, priority) values
  ('sustainable-barks', 'brand_partner', 'partnerships', 'Partnerships', 8, 75),
  ('sustainable-barks', 'guest', 'community', 'Community operations', 72, 35)
on conflict (app, lead_type) do update set
  owner_id=excluded.owner_id, owner_label=excluded.owner_label,
  sla_hours=excluded.sla_hours, priority=excluded.priority, active=true;

insert into growth_crm_templates(app, lead_type, step, template_key, subject_template, body_template, wait_hours) values
  ('sustainable-barks','brand_partner',1,'brand_partner_intro','A practical Sustainable Barks partnership','Thanks for reaching out. We will recommend the simplest useful way to test your product with hotel and shelter partners.',72),
  ('sustainable-barks','brand_partner',2,'brand_partner_followup','A suggested partnership pilot','Here is a focused pilot scope, the operating handoff, and the impact reporting we can provide.',120),
  ('sustainable-barks','guest',1,'guest_welcome','Welcome to Sustainable Barks','Thanks for joining. We will share concise dog stories and useful ways to support nearby rescue partners.',336)
on conflict (app, lead_type, step) do update set
  template_key=excluded.template_key, subject_template=excluded.subject_template,
  body_template=excluded.body_template, wait_hours=excluded.wait_hours;

commit;
