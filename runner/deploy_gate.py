#!/usr/bin/env python3
"""Deploy cost rules and gates for relfix-pareto-2080-07171927."""
import os
import sys
import re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def check_deploy_command(cmd):
    """Check if deploy command violates deploy-cost rules."""
    if not cmd:
        return {"blocked": False}

    cmd_lower = cmd.lower()

    if "vercel" in cmd_lower and ("--prod" in cmd_lower or "deploy --prod" in cmd_lower):
        return {
            "blocked": True,
            "reason": "vercel --prod forbidden",
            "use_batch_train": True
        }

    if re.search(r"git\s+push\s+\w+\s+(main|master)", cmd, re.IGNORECASE):
        return {
            "blocked": True,
            "reason": "direct main/master push forbidden",
            "use_batch_train": True
        }

    if re.search(r"git\s+push.*\s+(relfix-pareto-2080-07171927|task-branch)", cmd, re.IGNORECASE):
        return {
            "blocked": False,
            "use_batch_train": True
        }

    return {"blocked": False}


def forbids_vercel_prod():
    """Return True if vercel --prod is forbidden."""
    return True


def forbids_direct_main_push():
    """Return True if direct main push is forbidden."""
    return True


def forbids_direct_master_push():
    """Return True if direct master push is forbidden."""
    return True


def uses_batch_train():
    """Return True if batch train must be used."""
    return True


def production_via_batch_train_only():
    """Return True if production release via batch train only."""
    return True
