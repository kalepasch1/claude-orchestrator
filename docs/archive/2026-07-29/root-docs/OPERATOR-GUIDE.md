# Operator Guide — Steering the Fleet with Intent + Approvals

*One page. This is your entire job now. Everything else is automated.*

---

## 1. STATE INTENT (three channels, pick whichever is in reach)

**A. Drop-box (works today, most powerful).** Write a plain-English file and save it into
`intake/` (or a `PROMPT-<name>.md` at repo root). Freeform is fine — `prompt_factory` +
`planner` auto-decompose it into a contract-first task DAG, and the watcher queues it within
minutes. To pick a specific brain for a task, add one line: `model: opus|sonnet|haiku` or
(as vendor adapters land) `force_coder: codex|gemini|ollama|claude`. Nothing you drop executes
against prod directly — everything flows through gates.

    Example — the whole file can literally be:
    "Add CSV export to Apparently's licensing dashboard. Material. Prefer opus."

**B. Dashboard composer (as the terminal build lands).** Type the same intent at the web
dashboard → see the DAG preview → edit → queue. Vendor/model picker included. Ad-hoc live
sessions (you steer an agent turn-by-turn in any repo, any vendor) arrive with
`web-session-launcher`.

**C. Chat (Cowork/Claude Code — always available, for exceptions).** Sessions like today's
remain possible whenever you want hands-on work — they're now the exception, not the workflow.

**All AI vendors/models remain at your command at every step:** Claude (opus/sonnet/haiku),
Codex, Gemini, DeepSeek/Qwen/Codestral local via Ollama — named per-task in a drop, picked in
the composer, or auto-routed by the bandit when you don't care. The speed tier (Groq/Cerebras/
xAI) joins the same registry when its keys are added.

## 2. APPROVE (the only decisions that reach you)

Open the dashboard → **Approvals**. Cards arrive for exactly five things:
material merges/security changes · release-train prod promotions · experiment starts/promotions ·
shared-kernel extractions · weekly roadmap proposals (max 3 initiatives/app, EV-ranked).
Approve, deny, or comment. Everything non-material self-executes through gates
(tests → dev-batch → QA → prod) without you.

## 3. READ THE BRIEF (2 minutes, 7:00 AM daily)

Overnight merges/deploys · anything red · sentinel auto-fixes · queue trend · a max-3-item
"needs you" list. If the brief says healthy, you're done for the day.

## That's it.

Emergencies: the sentinel self-heals (DB outages, stuck runners, RAM clamps, checkout drift)
and escalates only what it can't fix — those arrive as cards too. Deep-dive tools when YOU
want them: dashboard → live run console (logs/diffs per task), `.runtime/sentinel.log`,
`REPORT-*.md` files. VS Code stays installed as a *viewer* — agents no longer need it and
neither do you.
