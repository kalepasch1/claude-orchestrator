#!/usr/bin/env python3
"""
go_to_market.py - turn an approved 'productizable' capability into shippable product surface
in a target app. Queues a build task in that app's repo to scaffold a landing page, pricing
stub, docs, and onboarding flow BEHIND A FEATURE FLAG (so it ships dark, then you flip it on).
Compresses "we have the capability" into "it's live and sellable".
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db, capability


def launch(slug, target_project, product_name):
    cap = capability.get(slug)
    if not cap:
        return {"ok": False, "error": "capability not found"}
    if cap["status"] != "productizable":
        return {"ok": False, "error": f"capability not productizable (status={cap['status']})"}
    proj = db.select("projects", {"select": "id", "name": f"eq.{target_project}"}) or []
    if not proj:
        return {"ok": False, "error": "target project not registered"}
    # ensure the capability is instantiated in the target app first
    inst = capability.instantiate(slug, target_project)
    if not inst.get("ok"):
        return inst
    prompt = (f"Productize the '{cap['name']}' capability as a new offering named "
              f"'{product_name}' in this app. Scaffold, behind a feature flag (default OFF): "
              f"(1) a landing/marketing page, (2) a pricing component (stub tiers), (3) user "
              f"docs, (4) an onboarding flow that invokes the capability. Capability summary: "
              f"{cap['summary']}. Contract: {cap['contract']}. Add tests for both flag states; "
              f"do NOT enable the flag. Keep the build green.")
    db.insert("tasks", {"project_id": proj[0]["id"], "slug": f"gtm-{slug}", "kind": "build",
                        "state": "QUEUED", "prompt": prompt})
    return {"ok": True, "queued": f"gtm-{slug}", "project": target_project}


if __name__ == "__main__":
    if len(sys.argv) >= 4:
        print(launch(sys.argv[1], sys.argv[2], sys.argv[3]))
    else:
        print("usage: go_to_market.py <capability-slug> <target-project> <product-name>")
