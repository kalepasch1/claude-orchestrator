# Ambient Teach-Skills Learning — Smrter, Apparently, Pareto, Tomorrow (always-on, no prompting)

Operator directive 2026-07-30. Embed Cowork-style "teach skills" capability so the hivemind/swarms
learn from ALL user activity continuously — the user just DOES their work; the system watches,
decomposes what it sees into tasks/sub-tasks/long-tasks/complex sequences, builds durable memory,
and autonomously proposes new skills/workflows. Smrter has partial groundwork; extend, don't fork.

## Architecture (uniform across the four apps)
1. ACTIVITY OBSERVER: a lightweight client-side event stream (navigation, edits, uploads, form
   flows, sequence timing) + server-side action log — consented per workspace, off by default for
   customer workspaces until enabled in settings, always-on for our own operator workspaces.
2. TASK MINER: a background pass (cheap/local models, batched, night-weighted) segments the
   activity stream into episodes -> infers the task being performed -> decomposes into steps ->
   classifies (atomic / long-running / complex-multi-session) -> names it.
3. SKILL SYNTHESIS: recurring episodes (>=3 similar) synthesize into a SKILL: trigger conditions,
   steps, required context/connections, expected artifacts — stored as versioned skill docs the
   agents can execute. Human-visible library per workspace: "we learned you do X weekly — want it
   automated?" One click converts a learned skill into a scheduled/triggered autonomous workflow
   (subject to the permissions framework + constitution: learned skills EXECUTE only within the
   user's risk ceiling; above it they propose).
4. MEMORY: episodes + skills feed the same workspace memory the advisors read (company_context),
   so gradients/advice improve from watching, not just from documents.
5. HIVEMIND SHARING: skill PATTERNS (not content) aggregate cross-workspace under the existing
   privacy rules (k>=3, no cross-workspace leakage) — "companies like you automate these 12
   things" becomes an onboarding asset.

## 50-500X hooks
- Shadow-run: before proposing automation, silently dry-run the learned skill next time the user
  starts the task and diff the outcome vs. the human's — propose only when the dry-run matches.
- Interruption rescue: recognize an abandoned mid-task episode and offer to finish it.
- Cross-app skill portability: a skill learned in Smrter (e.g., a filing-prep flow) is offered in
  Apparently where the same pattern appears.
- Skill marketplace seed: anonymized, admin-approved skills become templates for new customers.

## Guardrails
Consent + retention windows per workspace; no keystroke-level capture of sensitive fields;
skills never auto-execute above the risk ceiling; full audit of every autonomous execution.
