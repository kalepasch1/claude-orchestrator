# Handoff prompt — Cross-app capability learning (finish the build)

> Cowork already implemented the core in runner/ (import-clean) and applied live schema 0005.
> Built: privacy.py (PII/secret scrubber + differential-privacy counts), provenance.py
> (lineage + consent/residency), capability.py (registry: publish/version/instantiate/
> compose/retire, data-isolation enforced), distill.py (clean-room: generalized process ->
> capability + SYNTHETIC exemplars), maturity.py (evidence-gated promotion ladder),
> capability_radar.py (cross-app RICE product proposals, preference-gated), demand_mining.py
> (PII-stripped demand signals), go_to_market.py (queues product scaffolding behind a flag).
> Per the owner's decision there is NO compliance/expert-sign-off gate — but the data-plane
> isolation (privacy.scrub on every publish/distill) and consent checks (provenance) STAY.

```
Finish the cross-app capability layer in this repo. Modules above already exist; live DB is
at migration 0005 (capabilities, capability_versions, capability_provenance,
capability_instances, capability_evals). Work in small verified steps; report a checklist.

1. DASHBOARD (web/pages): add a "Capabilities" view — list each capability with status
   (experimental/trusted/productizable/retired), maturity score, domain, provenance
   (source app + consent), and which apps instantiate it (capability_instances). Add a
   "Capability radar" section; radar already files proposals into `approvals` (kind=proposal)
   so they show in the inbox — also surface them grouped here with a "Productize" button that
   calls go_to_market.launch(slug, target_app, product_name) via a small edge function.
   Keep `npm run build` green.

2. FEDERATED IMPROVEMENT LOOP: when an app runs a task that used a capability, write the real
   result back — update capability_evals.last_pass and recompute capability_versions
   .eval_pass_rate from those, so maturity.py reflects real-world performance. Wire this where
   runner.py records outcomes (tag tasks with the capability slug they instantiated).

3. VERSIONED-CONTRACT ENFORCEMENT: capability_instances pin a version. When a new version is
   published, diff the contract; if inputs/outputs changed incompatibly, file an approval for
   each consuming app instead of silently breaking it.

4. EMBEDDINGS for radar + dedup: use embeddings (context_embed/knowledge_embed) to match
   capabilities to app gaps semantically and to dedupe near-identical capabilities before
   publish. Keep the model-based path as fallback.

5. SCHEDULE (launchd): maturity.recompute (daily), capability_radar.run (weekly),
   demand_mining.run (weekly). Add REQUESTS_FILE or a `requests` table as the demand source.

6. SEED a safe end-to-end demo (no real customer data): take a GENERALIZED, public
   "entity-formation filing" process, run distill.distill(process_text, name='Entity formation
   filing', slug='entity-formation', domain='legal-ops', source_project='tomorrow',
   consent=True); add a couple synthetic evals so eval_pass_rate>0.9 and >=2 instances; run
   maturity.recompute() to promote it to 'productizable'; run capability_radar.run() and show
   it proposing the capability to another portfolio app; then go_to_market.launch() to queue
   the scaffolding task. Confirm privacy.scrub redacted everything and provenance recorded.

FINISH: checklist, capabilities + radar live in the dashboard, the federated loop wired, and
confirm privacy.scrub runs on every publish/distill path (show it).
```
