#!/usr/bin/env python3
"""Small operator CLI for multi-Mac runner control.

Examples:
  python3 fleetctl.py status
  python3 fleetctl.py bootstrap-defaults
  python3 fleetctl.py pull all
  python3 fleetctl.py restart Mac-2.local
  python3 fleetctl.py set ORCH_AUTO_PULL true
"""
import argparse
import datetime
import json
import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db
import fleet
import fleet_control


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _live_hosts():
    return [m["host"] for m in fleet.status().get("machines", []) if m.get("host")]


def _insert_control(action, target="all", params=None):
    params = dict(params or {})
    if target == "all":
        params.setdefault("expected_hosts", _live_hosts())
    row = {
        "action": action,
        "target": target,
        "params": params,
        "handled_by": [],
        "done": False,
        "requested_by": socket.gethostname(),
        "requested_at": _now(),
        "updated_at": _now(),
    }
    out = db.insert("fleet_control", row)
    return (out or [row])[0]


def _set_config(key, value):
    if not fleet_control._safe_key(key):
        raise SystemExit(f"refusing unsafe fleet config key: {key}")
    row = {
        "key": key,
        "value": str(value),
        "updated_by": socket.gethostname(),
        "updated_at": _now(),
    }
    db.insert("fleet_config", row, upsert=True)
    return row


def _recent_controls(limit=10):
    try:
        return db.select("fleet_control", {
            "select": "id,action,target,done,handled_by,last_error,requested_at,updated_at,params",
            "order": "requested_at.desc",
            "limit": str(limit),
        }) or []
    except Exception as e:
        return [{"error": str(e)}]


def cmd_status(_args):
    try:
        status = fleet.status()
    except Exception as e:
        status = {"error": str(e)}
    print(json.dumps({
        "fleet": status,
        "recent_controls": _recent_controls(),
    }, indent=2, default=str))


def cmd_set(args):
    print(json.dumps(_set_config(args.key, args.value), indent=2, default=str))


def cmd_bootstrap_defaults(_args):
    defaults = {
        "ORCH_AUTO_PULL": "true",
        "ORCH_AUTO_PULL_RESTART": "true",
        "ORCH_AUTO_PULL_MIN": "2",
        "ORCH_FLEET_TICK_S": "30",
        "ORCH_KEEPALIVE_STAY_RESIDENT": "true",
        "ORCH_KEEPALIVE_DUPLICATE_POLL_SECONDS": "60",
        "ORCH_RECOVERY_JUMP_QUEUE": "true",
        "ORCH_RELEASE_FIX_JUMP_QUEUE": "true",
        "ORCH_EVIDENCE_JUMP_QUEUE": "true",
    }
    rows = [_set_config(k, v) for k, v in defaults.items()]
    print(json.dumps({"configured": rows}, indent=2, default=str))


def cmd_control(args):
    params = {}
    if args.action == "git_pull":
        params["restart"] = not args.no_restart
    print(json.dumps(_insert_control(args.action, args.target, params), indent=2, default=str))


def main(argv=None):
    p = argparse.ArgumentParser(description="Control the orchestrator runner fleet through Supabase.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    b = sub.add_parser("bootstrap-defaults")
    b.set_defaults(func=cmd_bootstrap_defaults)

    sc = sub.add_parser("set")
    sc.add_argument("key")
    sc.add_argument("value")
    sc.set_defaults(func=cmd_set)

    for name, action in (("pull", "git_pull"), ("restart", "restart"), ("reload", "reload_config")):
        c = sub.add_parser(name)
        c.add_argument("target", nargs="?", default="all")
        c.add_argument("--no-restart", action="store_true")
        c.set_defaults(func=cmd_control, action=action)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
