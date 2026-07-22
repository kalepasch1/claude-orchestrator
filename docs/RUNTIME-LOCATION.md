# Runtime location (FDA-reset immunity)

The launchd runner executes from an **FDA-free clone outside `~/Documents`**, so a macOS
Full Disk Access reset can no longer crash-loop the fleet at startup.

- **Runtime checkout:** `~/claude-orchestrator` (git clone, tracks origin; kept current by
  `fleet_control.self_update()` via `ORCH_AUTO_PULL`, independent of any project `repo_path`).
- **Config (secrets):** `~/.claude-orchestrator/.env` (0600). The clone's `runner/.env` is a
  symlink to it, so `keepalive.sh`'s default `$RUNNER_DIR/.env` resolves to the canonical file.
- **Launcher preference:** `ClaudeRunner.app/Contents/Resources/launcher.sh` prefers
  `~/claude-orchestrator`; the `com.claudeorchestrator.*` launchd plists set
  `CLAUDE_ORCH_REPO=~/claude-orchestrator` + `WorkingDirectory` to the clone runner dir.
- **Login autostart:** `~/.zprofile` starts `keepalive.sh` from `~/claude-orchestrator`
  (shares the same `.runtime/runner.lock`, so it never double-starts).
- **Why `~/Documents` is the problem:** it is TCC-protected; a launchd process without FDA
  cannot read `.env`, `keepalive.sh`, or `runner.py` there. Nothing under `~/` top-level or
  `~/.claude-orchestrator` is TCC-gated.

Project `repo_path` values (beethoven included) intentionally stay under `~/Documents` so the
second Mac (which checks out there) is unaffected; only THIS Mac's *runtime* was relocated.
To harden the other Mac, repeat: clone to `~/claude-orchestrator`, copy `.env` to
`~/.claude-orchestrator/.env`, repoint its launcher/plists/`.zprofile`.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `runner.py` crash-loops after macOS update | FDA revoked; runtime still under `~/Documents` | Move runtime to `~/claude-orchestrator` per above |
| `.env` not found at startup | Symlink broken or `~/.claude-orchestrator/.env` missing | Re-create: `ln -sf ~/.claude-orchestrator/.env runner/.env` |
| Double-start (two runners) | Lock file path mismatch between `keepalive.sh` and launchd | Ensure both use `.runtime/runner.lock` in the same clone |
