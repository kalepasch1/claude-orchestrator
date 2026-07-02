#!/usr/bin/env python3
"""
stripe_revenue.py - auto-populate app_revenue from Stripe so the governor + roadmap run on REAL numbers,
no manual entry. Reads active subscriptions per Stripe account and upserts MRR + active subscriber count
into app_revenue, keyed by the app name you map. Guarded: only runs if STRIPE_API_KEY is set (read-only
scope is enough). One account -> one app by default; map multiple via STRIPE_APP_MAP (json name->key env).

Never writes to Stripe. Schedule daily. Read-only, key stays server-side.
"""
import os, sys, json, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

BASE = "https://api.stripe.com/v1"


def _get(path, key, params=""):
    req = urllib.request.Request(BASE + path + params,
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def _mrr_for(key):
    """Sum monthly-normalized recurring revenue over active subscriptions."""
    mrr = 0.0
    count = 0
    starting_after = ""
    for _ in range(20):  # up to 2000 subs
        params = "?status=active&limit=100" + (f"&starting_after={starting_after}" if starting_after else "")
        d = _get("/subscriptions", key, params)
        for s in d.get("data", []):
            count += 1
            for it in (s.get("items", {}) or {}).get("data", []):
                pr = it.get("price", {}) or {}
                amt = (pr.get("unit_amount") or 0) / 100.0 * (it.get("quantity") or 1)
                interval = (pr.get("recurring", {}) or {}).get("interval", "month")
                mrr += amt / 12.0 if interval == "year" else (amt if interval == "month" else amt)
        if d.get("has_more") and d.get("data"):
            starting_after = d["data"][-1]["id"]
        else:
            break
    return round(mrr, 2), count


def run():
    key = os.environ.get("STRIPE_API_KEY", "").strip()
    if not key:
        print("stripe_revenue: STRIPE_API_KEY not set — skipping (manual app_revenue still works)")
        return 0
    # map account -> app; default single-app via STRIPE_DEFAULT_APP
    app_map = {}
    try:
        app_map = json.loads(os.environ.get("STRIPE_APP_MAP", "") or "{}")
    except Exception:
        pass
    default_app = os.environ.get("STRIPE_DEFAULT_APP", "")
    try:
        mrr, subs = _mrr_for(key)
    except urllib.error.HTTPError as e:
        print(f"stripe_revenue: Stripe API error {e.code} — check the key's read scope"); return 0
    except Exception as e:
        print(f"stripe_revenue: {e}"); return 0
    apps = list(app_map.values()) or ([default_app] if default_app else [])
    n = 0
    for app in apps:
        db.insert("app_revenue", {"app": app, "mrr_usd": mrr, "active_users": subs,
                                  "updated_at": "now()"}, upsert=True)
        n += 1
    print(f"stripe_revenue: MRR ${mrr} across {subs} active subs -> updated {n} app(s)")
    return n


if __name__ == "__main__":
    run()
