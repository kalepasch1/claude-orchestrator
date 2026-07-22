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

## Verification

To confirm the runtime is correctly located outside TCC-protected paths:

```bash
# Should resolve to ~/claude-orchestrator, NOT ~/Documents/...
launchctl print system/com.claudeorchestrator.runner 2>/dev/null | grep WorkingDirectory
# .env symlink should point to ~/.claude-orchestrator/.env
ls -la ~/claude-orchestrator/runner/.env
```
