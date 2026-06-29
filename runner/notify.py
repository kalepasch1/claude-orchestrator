#!/usr/bin/env python3
"""
notify.py - one place to send a short alert to you (Slack + email via scripts/notify.sh,
falling back to stdout). Used for the things you actually want to hear about WITHOUT
babysitting: account rotation, all-accounts-exhausted, cost circuit tripped, cap reached.
"""
import os, subprocess

_SH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "notify.sh")


def send(msg: str) -> None:
    msg = str(msg)
    try:
        if os.path.exists(_SH):
            subprocess.run(["bash", _SH, msg], check=False, timeout=30)
            return
    except Exception:
        pass
    print(f"[notify] {msg}")


if __name__ == "__main__":
    import sys
    send(" ".join(sys.argv[1:]) or "test notification")
