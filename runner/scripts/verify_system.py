#!/usr/bin/env python3
"""Quick system health check — run from runner/ directory."""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import db

print("=" * 60)
print("SYSTEM HEALTH CHECK")
print("=" * 60)

# 1. Accounts
print("\n[1] ACCOUNTS")
try:
    rows = db.select("accounts", {"select": "name,type,config_dir,priority,cooldown_until,machine", "order": "priority.asc"})
    for r in (rows or []):
        cd = r.get("cooldown_until") or "none"
        m = r.get("machine") or "any"
        print(f"  {r['priority']}. {r['name']} ({r['type']}) config={r.get('config_dir')} machine={m} cooldown={cd}")
    print(f"  TOTAL: {len(rows or [])} accounts")
except Exception as e:
    print(f"  ERROR: {e}")

# 2. Runner heartbeats
print("\n[2] RUNNER HEARTBEATS")
try:
    rows = db.select("runner_heartbeats", {"select": "runner_id,last_seen,active_tasks,status", "order": "last_seen.desc", "limit": "5"})
    for r in (rows or []):
        print(f"  {r['runner_id']}: status={r.get('status','?')} active={r.get('active_tasks',0)} last_seen={r.get('last_seen','?')}")
    if not rows:
        print("  No heartbeats found")
except Exception as e:
    print(f"  ERROR: {e}")

# 3. Task queue
print("\n[3] TASK QUEUE")
try:
    for state in ["QUEUED", "RUNNING", "DONE", "BLOCKED", "FAILED"]:
        all_rows = db.select("tasks", {"select": "id", "state": f"eq.{state}"})
        print(f"  {state}: {len(all_rows or [])}")
except Exception as e:
    print(f"  ERROR: {e}")

# 4. Controls (new modules)
print("\n[4] NEW MODULE STATE")
for key in ["capacity_pacer", "exhaustion_signal", "surge_plan"]:
    try:
        rows = db.select("controls", {"select": "key,value", "key": f"eq.{key}"})
        if rows and rows[0].get("value"):
            v = rows[0]["value"]
            d = json.loads(v) if isinstance(v, str) else v
            if key == "exhaustion_signal":
                print(f"  {key}: all_exhausted={d.get('all_exhausted')}, cooling={d.get('accounts_cooling')}/{d.get('total_accounts')}, reset_in={d.get('earliest_reset_min',0)}min")
            elif key == "surge_plan":
                print(f"  {key}: {d.get('task_count',0)} tasks planned")
            else:
                print(f"  {key}: updated={d.get('last_updated','never')}")
        else:
            print(f"  {key}: not yet populated")
    except Exception as e:
        print(f"  {key}: ERROR {e}")

# 5. Module import check
print("\n[5] NEW MODULE IMPORTS")
for mod in ["capacity_pacer", "account_partition", "generator_feedback", "exhaustion_signal", "surge_planner"]:
    try:
        __import__(mod)
        print(f"  OK  {mod}")
    except Exception as e:
        print(f"  FAIL {mod}: {e}")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
