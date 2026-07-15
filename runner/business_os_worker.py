#!/usr/bin/env python3
"""Claim and execute Business OS creative work without bypassing review or spend caps."""
import datetime
import json
import os
import socket

import db
import creative_dispatch

CAPABILITY_PROVIDERS = {
    "image": ("bfl", "ideogram"),
    "motion": ("kling",),
    "3d": ("meshy",),
}


def _now_plus(minutes):
    return (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)).isoformat()


def _bounded_int(value, default, minimum, maximum):
    try:
        return max(minimum, min(int(value), maximum))
    except (TypeError, ValueError):
        return default


def _provider(job, configured):
    supported = CAPABILITY_PROVIDERS.get(job.get("capability"), ())
    preferred = [job.get("selected_provider"), *(job.get("provider_candidates") or []), *supported]
    return next((name for name in preferred if name in supported and name in configured), None)


def _proof(job, result, effect):
    try:
        db.insert("capability_activation_proofs", {
            "capability": f"business_os:creative_{job.get('capability')}",
            "invocation_key": f"creative-job:{job['id']}:{job.get('attempts', 1)}",
            "invoked": True,
            "effect": effect,
            "outcome": result.get("status", "error"),
            "metrics": {
                "provider": result.get("provider"),
                "cost_usd": result.get("cost_usd", 0),
                "elapsed_s": result.get("elapsed_s", 0),
                "review_required": True,
            },
        }, upsert=True)
    except Exception:
        pass


def _recover_configured(configured):
    """Make jobs runnable when a provider key is added after the job was drafted."""
    try:
        waiting = db.select("creative_production_jobs", {
            "select": "id,capability,selected_provider,provider_candidates",
            "status": "eq.connector_required", "attempts": "lt.3", "limit": "20",
        }) or []
        for job in waiting:
            provider = _provider(job, configured)
            if provider:
                db.update("creative_production_jobs", {"id": job["id"]}, {
                    "status": "ready", "selected_provider": provider,
                    "next_attempt_at": None, "last_error": None,
                })
    except Exception:
        return


def _heartbeat(worker, configured):
    try:
        db.insert("creative_runtime_status", {
            "id": True, "providers": sorted(configured), "worker": worker,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }, upsert=True)
    except Exception:
        pass


def _generate(job, provider):
    controls = job.get("controls") or {}
    prompt = job.get("brief") or ""
    if job.get("capability") == "image":
        return creative_dispatch.generate_image(
            prompt, provider=provider,
            width=_bounded_int(controls.get("width"), 1024, 256, 2048),
            height=_bounded_int(controls.get("height"), 1024, 256, 2048),
            text_in_image=bool(controls.get("text_in_image", False)),
        )
    if job.get("capability") == "motion":
        return creative_dispatch.generate_video(
            prompt, provider=provider,
            duration_s=_bounded_int(controls.get("duration_s"), 5, 1, 30),
        )
    if job.get("capability") == "3d":
        return creative_dispatch.generate_3d(prompt, provider=provider)
    return {"status": "error", "provider": provider, "errors": ["unsupported capability"]}


def run_once(worker=None):
    worker = worker or f"{socket.gethostname()}:{os.getpid()}"
    configured = set(creative_dispatch.available())
    _heartbeat(worker, configured)
    _recover_configured(configured)
    try:
        claimed = db.rpc("claim_creative_production_job", {"p_worker": worker}) or []
    except Exception as exc:
        # Rollouts may briefly run the worker before its migration lands. Keep the
        # scheduler healthy and let the next interval retry after schema convergence.
        return {"status": "control_plane_unavailable", "error": str(exc)[:500]}
    if not claimed:
        return {"status": "idle"}
    job = claimed[0] if isinstance(claimed, list) else claimed
    provider = _provider(job, configured)
    if not provider:
        message = "No supported provider credential is configured for this capability"
        db.update("creative_production_jobs", {"id": job["id"]}, {
            "status": "connector_required", "last_error": message,
            "claimed_by": None, "claimed_at": None,
        })
        if job.get("action_run_id"):
            db.update("business_action_runs", {"id": job["action_run_id"]}, {"state": "blocked", "outcome": {"reason": message}})
        result = {"status": "connector_required", "errors": [message]}
        _proof(job, result, False)
        return result

    result = _generate(job, provider)
    ok = result.get("status") in ("ok", "success", "completed", "succeeded") and bool(result.get("output_url"))
    if ok:
        db.update("creative_production_jobs", {"id": job["id"]}, {
            "status": "review", "selected_provider": provider, "outputs": [result],
            "last_error": None, "claimed_by": None, "claimed_at": None,
            "provenance": {**(job.get("provenance") or {}), "runtime": "creative_dispatch", "review_required": True},
        })
        if job.get("action_run_id"):
            db.update("business_action_runs", {"id": job["action_run_id"]}, {
                "state": "completed", "outcome": {"creative_job_id": job["id"], "status": "review", "provider": provider},
            })
    else:
        message = "; ".join(str(item) for item in (result.get("errors") or ["provider generation failed"]))[:1000]
        capped = "cap" in message.lower() and ("hour" in message.lower() or "day" in message.lower())
        attempts = int(job.get("attempts") or 1)
        retry = capped or attempts < 3
        db.update("creative_production_jobs", {"id": job["id"]}, {
            "status": "ready" if retry else "failed", "last_error": message,
            "next_attempt_at": _now_plus(60 if capped else 5) if retry else None,
            "claimed_by": None, "claimed_at": None,
        })
        if not retry and job.get("action_run_id"):
            db.update("business_action_runs", {"id": job["action_run_id"]}, {"state": "blocked", "outcome": {"reason": message}})
    _proof(job, result, ok)
    return {**result, "job_id": job["id"], "review_required": ok}


if __name__ == "__main__":
    print(json.dumps(run_once(), default=str))
