#!/usr/bin/env python3
"""
growth_creative_gen.py — turns draft creatives (derivatives + annotate->regen variants) into
reviewable assets, then routes them to the designer via auto-triage on the brand score.

Registered as the 'creative_gen' loop type. Pluggable image-gen + vision-brand-score seams: if an
image model / vision scorer is configured it generates + scores; otherwise it fails soft (leaves the
asset for the designer to attach). Nothing is published without the designer's approval (creative_gate).
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db

IMG_ENDPOINT = os.environ.get("IMAGE_GEN_URL")     # optional image-gen seam
VISION_ENDPOINT = os.environ.get("VISION_SCORE_URL")  # optional vision brand-scorer seam
BATCH = int(os.environ.get("CREATIVE_GEN_BATCH", "20"))


def _generate(prompt, brand_kit):
    if not IMG_ENDPOINT:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(IMG_ENDPOINT, method="POST",
              data=json.dumps({"prompt": prompt, "brand": brand_kit}).encode(),
              headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read()).get("url")
    except Exception as e:
        print(f"creative_gen image error: {e}"); return None


def _brand_score(url, brand_kit):
    if not VISION_ENDPOINT or not url:
        return None
    try:
        import urllib.request
        req = urllib.request.Request(VISION_ENDPOINT, method="POST",
              data=json.dumps({"url": url, "brand": brand_kit}).encode(),
              headers={"Content-Type": "application/json"})
        return float(json.loads(urllib.request.urlopen(req, timeout=30).read()).get("score"))
    except Exception as e:
        print(f"creative_gen score error: {e}"); return None


def run():
    drafts = db.select("growth_creative", {"select": "id,app,gen_prompt", "status": "eq.draft", "limit": str(BATCH)}) or []
    for cr in drafts:
        kit = (db.select("growth_brand_kit", {"select": "spec", "app": f"eq.{cr['app']}"}) or [{}])[0].get("spec", {})
        url = _generate(cr.get("gen_prompt", ""), kit)
        score = _brand_score(url, kit)
        patch = {"status": "in_review"}
        if url:
            patch["asset_url"] = url; patch["thumb_url"] = url
        if score is not None:
            patch["brand_score"] = round(score, 3)
        db.update("growth_creative", {"id": cr["id"]}, patch)
        # auto-triage on the score: obvious on/off-brand handled; borderline stays for the designer
        if score is not None:
            db.rpc("auto_triage_creative", {"p_creative_id": cr["id"], "p_hi": 0.85, "p_lo": 0.4})
    print(f"creative_gen: processed {len(drafts)} drafts")


if __name__ == "__main__":
    run()
