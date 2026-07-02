# Cloud runner — setup + cost/value optimization

The orchestrator's value depends entirely on the runner being **up 24/7**. A laptop process keeps
dying; move it to a cheap always-on VM under systemd (`deploy/runner.service`, `Restart=always`), with
the pg_cron dead-man's-switch as the backstop.

## Where the cost actually is (this is the key insight)
The VM is **not** your cost driver — the **model API spend is** (~$40/day cap already enforced by the
runner's budget + waste guard). Local compute is just polling + orchestrating Claude Code. So:

- **Right-size small, not big.** 2 vCPU / 4 GB is plenty (heavy lifting is the API, not the box).
- **Optimize the expensive layer, not the cheap one.** The 20-500× cost/value lever is **`app_triage`
  routing every call to the cheapest capable model** (already built) + the $/day cap + the "waste
  guard" that pauses any project spending >$5/6h with nothing merged. Keep those on. A bigger VM buys
  you nothing; cheaper model routing buys you everything.

## Recommended VM (cost/value optimal)
| Option | Spec | ~Cost/mo | Notes |
|---|---|---|---|
| **Hetzner CX22** | 2 vCPU / 4 GB | **~$5** | best €/value; EU/US regions |
| DigitalOcean / Fly.io | 2 vCPU / 4 GB | ~$18–24 | simplest, US-based |
| Oracle Cloud Free | 4 OCPU Ampere / 24 GB | **$0** | genuinely free always-on tier — highest value if you tolerate setup |

A fixed ~$5/mo box + disciplined model routing beats any autoscaling scheme here (the runner is a
long-lived poller, so scale-to-zero adds cold-start pain for no real saving). **Do not** put it on a
big GPU/compute instance — there's no local ML.

## Further cost controls (already have hooks)
- `PORTFOLIO_WEEKLY_BUDGET` gates the growth/BD spend loops.
- `provider_budgets` + the waste guard cap per-project burn.
- `queue_groom` culls no-op tasks so you never pay to re-run dead work.
- Set the model floor per task_class in `app_triage` so "mechanical/qa" never uses a premium model.

## One-time VM setup
```bash
sudo mkdir -p /opt && cd /opt
git clone <your-repo-url> claude-orchestrator && cd claude-orchestrator/runner
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt   # if present
cp .env.example .env   # then fill: SUPABASE_URL/SERVICE_KEY, ANTHROPIC_API_KEY, VERCEL_TOKEN,
                       # SUPABASE_ACCESS_TOKEN, ORCH_PUSH_ON_MERGE=true, ENABLE_PROACTIVE_LOOPS=true
gh auth login          # so it can push + open PRs (git push origin drives Vercel)
git config --global user.email you@domain ; git config --global user.name "orchestrator"
sudo cp ../deploy/runner.service /etc/systemd/system/orchestrator-runner.service
sudo systemctl daemon-reload && sudo systemctl enable --now orchestrator-runner
journalctl -u orchestrator-runner -f
```
The runner needs **git push + `gh` auth for every app repo** it deploys (that's what reaches Vercel).
Clone each app repo it manages onto the VM at the paths in the `projects` table, or point those paths
at the VM's checkouts.

## Verify it's working (the whole point)
- `select * from runner_alerts order by created_at desc;` → should stay empty (no downtime).
- `select * from portfolio_health;` → deploy_state flips to READY per app as merges push.
- `select * from deploy_status;` + Vercel → green deploys following merges.
