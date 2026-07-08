#!/usr/bin/env python3
"""
One-shot script: add kale@smrter.us as the third subscription account
and clear all cooldown state so the runner resumes immediately.

Run from runner/:  python3 scripts/add_smrter_account.py
"""
import os, sys, json, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "scripts"
                else os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db

# 1. Insert the third account
print("[1/3] Adding kale@smrter.us to accounts table...")
try:
    db.upsert("accounts", {
        "name": "kale@smrter.us",
        "type": "subscription",
        "config_dir": "~/.claude-smrter",
        "api_key_env": None,
        "machine": None,       # usable by any Mac in the fleet
        "priority": 3,         # after gmail (1) and heretomorrow (2)
        "cooldown_until": None,
    })
    print("   ✓ kale@smrter.us inserted (priority=3, config_dir=~/.claude-smrter)")
except Exception as e:
    print(f"   ✗ insert failed: {e}")

# 2. Clear all cooldown state
print("[2/3] Clearing cooldown state for all accounts...")
for acct_name in ["kalepasch@gmail.com", "kale@heretomorrow.us", "kale@smrter.us"]:
    try:
        db.update("accounts", {"name": acct_name}, {"cooldown_until": None})
        print(f"   ✓ {acct_name} cooldown cleared")
    except Exception as e:
        print(f"   ✗ {acct_name}: {e}")

# 3. Clear local cooldown state file
HOME = os.environ.get("CLAUDE_ORCH_HOME", os.path.expanduser("~/.claude-orchestrator"))
state_file = os.path.join(HOME, "accounts_state.json")
exhausted_file = os.path.join(HOME, "claude_exhausted.json")
for f in [state_file, exhausted_file]:
    try:
        if os.path.exists(f):
            os.remove(f)
            print(f"   ✓ removed {f}")
        else:
            print(f"   ✓ {f} already clean")
    except Exception as e:
        print(f"   ✗ {f}: {e}")

# 4. Check if ~/.claude-smrter auth exists
smrter_dir = os.path.expanduser("~/.claude-smrter")
if not os.path.isdir(smrter_dir):
    print(f"\n⚠️  ~/.claude-smrter does not exist yet.")
    print(f"   Run this in Terminal to authenticate:")
    print(f"   CLAUDE_CONFIG_DIR=~/.claude-smrter claude auth login")
    print(f"   Then log in with kale@smrter.us credentials.\n")
else:
    print(f"   ✓ {smrter_dir} exists")

# 5. Verify
print("[3/3] Verifying accounts table...")
try:
    rows = db.select("accounts", {"select": "name,type,config_dir,priority,cooldown_until", "order": "priority.asc"})
    for r in (rows or []):
        print(f"   {r['priority']}. {r['name']} ({r['type']}) config={r.get('config_dir')} cooldown={r.get('cooldown_until')}")
    print(f"\n✓ {len(rows or [])} accounts configured. Runner will pick up the first healthy one on next poll.")
except Exception as e:
    print(f"   ✗ verify failed: {e}")
