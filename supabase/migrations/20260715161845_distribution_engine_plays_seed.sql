-- Grassroots play library. Each play separates AGENT steps (autonomous) from HUMAN steps
-- (only-a-human-can-do, specific + detailed). human_steps entries are templates the engine turns
-- into growth_human_task rows with real targets.
insert into public.growth_distribution_play(slug, name, channel, objective, agent_steps, human_steps, cost_usd, expected_reach, human_minutes, cycle_days, score) values

 ('reddit-value-answers','Reddit value-first answers','reddit_community','signups',
  '["Monitor target subreddits for high-intent questions (listening rules -> ingest_signal)","Draft a genuinely useful, non-promotional answer grounded in the corpus; CADE-gate it","Queue the answer for approval (send gate applies)","Track link clicks via tracked links; learn which subs convert"]'::jsonb,
  '[{"kind":"community_answer","title_template":"Answer the top {subreddit} thread: {thread_title}","why":"Highest-intent question this week; your named expertise makes the answer credible in a way a bot answer is not.","effort_minutes":15,"expected_impact":400,"prep":{"needs":"Your 2-line personal take + permission to use your name"}}]'::jsonb,
  0, 2000, 15, 3, 0.72),

 ('show-hn-launch','Show HN launch','hn_community','signups',
  '["Draft the Show HN title + first comment (technical, humble, specific)","Prepare the demo link, screenshots, and a 60s loom script","Monitor + draft replies to every comment within minutes for approval","Track referral traffic + signups"]'::jsonb,
  '[{"kind":"write_post","title_template":"Post Show HN for {app} at 8-9am ET Tue-Thu","why":"HN requires a real human account with history; timing drives the whole outcome.","effort_minutes":20,"expected_impact":5000,"prep":{"needs":"Your HN account; post from your own hands"}},{"kind":"demo","title_template":"Stay online 3h to reply to HN comments on {app}","why":"Founder replies in-thread are the single biggest driver of front-page staying power.","effort_minutes":180,"expected_impact":4000,"prep":{}}]'::jsonb,
  0, 9000, 200, 90, 0.68),

 ('product-hunt-launch','Product Hunt launch','product_hunt','signups',
  '["Build the listing: tagline, gallery, first comment, maker story","Warm the audience 2 weeks out with build-in-public posts","Draft day-of DMs to supporters (queued for approval)","Track PH referral -> signups"]'::jsonb,
  '[{"kind":"intro_request","title_template":"Line up a hunter + 20 supporters for {app} PH launch","why":"PH ranking is decided in the first 4 hours by real accounts you personally asked.","effort_minutes":90,"expected_impact":3000,"prep":{"needs":"Your list of 20 people who would genuinely upvote"}},{"kind":"demo","title_template":"Be live in PH comments launch day (12am PT start)","why":"Maker responsiveness drives ranking + conversion.","effort_minutes":180,"expected_impact":2500,"prep":{}}]'::jsonb,
  0, 6000, 270, 90, 0.7),

 ('build-in-public','Build in public (founder-led)','build_in_public','awareness',
  '["Turn each merged feature / metric into a specific, numbers-first post","CADE-gate + schedule at best_post_slot on the founder account","Atomize into X/LinkedIn/Threads variants; bandit the hooks","Report which narratives drive profile visits -> signups"]'::jsonb,
  '[{"kind":"record_video","title_template":"Record a 60-90s raw video: {topic}","why":"Face-to-camera founder video outperforms text 3-5x on reach and is the one asset agents cannot fake.","effort_minutes":20,"expected_impact":1500,"prep":{"script":"Hook (problem) -> what you shipped -> the number -> what is next. No script reading; one take is fine."}}]'::jsonb,
  0, 4000, 20, 3, 0.8),

 ('podcast-circuit','Podcast guest circuit','podcast','credibility',
  '["Build a ranked list of shows whose audience == the ICP (size, recency, guest profile)","Draft a specific, flattering, angle-led pitch per show (CADE-gated, queued for approval)","Prep a one-pager + 5 talking points + 3 stories per booked show","Repurpose each episode into 6 clips + 1 article"]'::jsonb,
  '[{"kind":"podcast_pitch","title_template":"Approve + send pitch to {show} (host: {host})","why":"Host relationships convert on a real name, not a bot.","effort_minutes":10,"expected_impact":800,"prep":{}},{"kind":"speak","title_template":"Record the {show} episode","why":"Borrowed trust from an aligned audience; evergreen authority asset.","effort_minutes":60,"expected_impact":3000,"prep":{"needs":"Talking points + 3 stories prepared by the agent"}}]'::jsonb,
  0, 5000, 70, 14, 0.75),

 ('conference-hallway','Conference hallway track','conference','partnership',
  '["Scan the attendee/speaker list for ICP + partners; rank by value","Build a dossier per target (their work, mutuals, a specific opener)","Draft pre-conference intro messages for approval","Draft same-day follow-ups + next steps"]'::jsonb,
  '[{"kind":"attend_event","title_template":"Attend {event} ({date}) — {n} ranked targets will be there","why":"Rooms convert relationships at a rate no channel matches; the agent cannot be in the room.","effort_minutes":480,"expected_impact":4000,"prep":{"includes":"Ranked target list, per-person dossier + opener, schedule of where/when to find them"}},{"kind":"call_person","title_template":"Meet {person} ({role} @ {company}) at {event}","why":"Specifically ranked as a top partner/ICP target attending.","effort_minutes":20,"expected_impact":1200,"prep":{}}]'::jsonb,
  500, 5000, 500, 60, 0.66),

 ('warm-intro-engine','Warm intro engine','warm_intro','signups',
  '["Mine the network graph (email/LinkedIn/calendar) for warm paths to ICP targets","Rank targets by path strength x fit x timing signal (job change, funding, post)","Draft the ask-for-intro message + the forwardable blurb","Track intro -> meeting -> conversion"]'::jsonb,
  '[{"kind":"call_person","title_template":"Ask {connector} for an intro to {target} ({company})","why":"Warm intros convert ~10x cold; only you can credibly ask your own contact.","effort_minutes":5,"expected_impact":600,"prep":{"includes":"Pre-written ask + forwardable blurb; you just hit send"}}]'::jsonb,
  0, 1500, 5, 7, 0.85),

 ('newsletter-swap','Newsletter swaps & features','newsletter_swap','signups',
  '["Find aligned newsletters (same ICP, 1k-50k subs) and their contact","Draft a specific swap/feature proposal with a written blurb ready to run","Queue outreach for approval; track referral signups per partner"]'::jsonb,
  '[{"kind":"intro_request","title_template":"Approve swap proposal to {newsletter} ({subs} subs)","why":"Borrowed list trust; a named founder ask lands where a bot ask does not.","effort_minutes":10,"expected_impact":900,"prep":{}}]'::jsonb,
  0, 2500, 10, 14, 0.7),

 ('seo-pillar-programmatic','SEO pillar + programmatic','seo_content','signups',
  '["Mine the corpus + query logs for real demand (gap flywheel)","Generate pillar + programmatic pages grounded in authorities, CADE-gated","Internal-link + submit; monitor rank/impressions -> iterate"]'::jsonb,
  '[{"kind":"write_post","title_template":"Add your named POV to the {topic} pillar page","why":"E-E-A-T: a named expert byline is what makes this rank and convert; agents supply the rest.","effort_minutes":25,"expected_impact":2000,"prep":{}}]'::jsonb,
  0, 8000, 25, 30, 0.6),

 ('directory-blitz','Directory blitz','directory_blitz','awareness',
  '["Maintain a list of relevant directories/marketplaces per app","Auto-fill + submit listings with on-brand copy + assets","Track referral + backlink authority"]'::jsonb,
  '[]'::jsonb,
  0, 1500, 0, 30, 0.55),

 ('creator-seeding','Micro-creator seeding','creator_seeding','awareness',
  '["Identify niche creators whose audience == ICP (1k-50k, high engagement)","Draft a specific, non-templated offer (free access + a real reason to care)","Queue outreach for approval; track per-creator conversion"]'::jsonb,
  '[{"kind":"record_video","title_template":"Record a 2-min personal demo for {creator}","why":"A personal demo video converts creator partnerships far better than a press kit.","effort_minutes":15,"expected_impact":1200,"prep":{}}]'::jsonb,
  100, 3000, 15, 14, 0.62),

 ('referral-loop','Referral loop / waitlist','referral_waitlist','signups',
  '["Instrument invite links per user (tracked links)","Add a reward/queue-jump mechanic; auto-nudge at the right moment","A/B the incentive via the bandit; report k-factor"]'::jsonb,
  '[]'::jsonb,
  0, 3000, 0, 7, 0.65)

on conflict (slug) do update set name=excluded.name, agent_steps=excluded.agent_steps,
  human_steps=excluded.human_steps, expected_reach=excluded.expected_reach, score=excluded.score;;
