# Account Pool — Usage Guide

`runner/account_pool.py` rotates among configured credentials when one
account hits its rate limit, keeping the runner from stalling.

## Configuration

Create `~/.claude-orchestrator/accounts.json`:

```json
[
  {"name": "personal-max", "type": "login", "config_dir": "~/.claude"},
  {"name": "team-api", "type": "api", "api_key_env": "ANTHROPIC_API_KEY_TEAM"}
]
```

## Behavior

- On rate-limit detection the pool advances to the next credential.
- Credentials are cycled round-robin; exhausted ones cool down automatically.
- Only add credentials you are authorized to use — this is not for evading
  limits with throwaway accounts.
