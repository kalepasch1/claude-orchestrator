#!/usr/bin/env python3
"""Execute policy-authorized virtual-executive saga steps and predict slow human-drain work."""
import datetime
import hashlib
import json
import os
import socket
import urllib.error
import urllib.request

import db


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _adapter_url(provider):
    key = "BUSINESS_AGENT_" + str(provider or "PROFESSIONAL").upper().replace("-", "_") + "_URL"
    return os.environ.get(key) or os.environ.get("BUSINESS_AGENT_ADAPTER_URL")


def _call_adapter(step, saga, agent):
    url = _adapter_url(step.get("connector_provider"))
    if not url:
        return {"ok": False, "retryable": True, "error": "approved connector adapter is not configured"}
    body = json.dumps({
        "version": "business-saga/v1", "step_id": step["id"], "saga_id": saga["id"],
        "agent": agent.get("agent_key"), "operation": step.get("operation"),
        "provider": step.get("connector_provider"), "scopes": step.get("connector_scope") or [],
        "input": step.get("input") or {}, "idempotency_key": step.get("idempotency_key"),
        "authority_scope": step.get("authority_scope"), "approval_id": step.get("approval_id"),
    }, default=str).encode()
    request = urllib.request.Request(url.rstrip("/") + "/v1/business-saga/execute", data=body, method="POST", headers={
        "content-type": "application/json", "x-fleet-secret": os.environ.get("FLEET_SHARED_SECRET", ""),
        "idempotency-key": step.get("idempotency_key") or "",
    })
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            result = json.loads(response.read().decode() or "{}")
        if result.get("ok") and (result.get("receipt_digest") or result.get("external_ref")):
            return result
        return {"ok": False, "retryable": False, "error": "adapter response lacked a verifiable execution receipt"}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "retryable": True, "error": str(exc)[:500]}


def _finish_saga(saga_id):
    pending = db.select("agentic_business_saga_steps", {
        "select": "id,state", "saga_id": f"eq.{saga_id}",
        "state": "not.in.(completed,skipped,compensated)", "limit": "1",
    }) or []
    if not pending:
        db.update("agentic_business_sagas", {"id": saga_id}, {
            "state": "completed", "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "outcome": {"status": "completed", "exactly_once": True, "receipts_required": True},
        })


def execute_once(worker=None):
    worker = worker or f"{socket.gethostname()}:{os.getpid()}"
    try:
        claimed = db.rpc("claim_agentic_business_saga_step", {"p_worker": worker}) or []
    except Exception as exc:
        return {"status": "control_plane_unavailable", "error": str(exc)[:500]}
    if not claimed:
        return {"status": "idle"}
    step = claimed[0] if isinstance(claimed, list) else claimed
    saga_rows = db.select("agentic_business_sagas", {"select": "*", "id": f"eq.{step['saga_id']}", "limit": "1"}) or []
    saga = saga_rows[0] if saga_rows else {}
    agent_rows = db.select("business_function_agents", {"select": "*", "id": f"eq.{saga.get('agent_id')}", "limit": "1"}) or []
    agent = agent_rows[0] if agent_rows else {}
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if not step.get("external_effect"):
        output = {"status": "completed", "artifact": "internal_control_record", "operation": step.get("operation")}
        db.update("agentic_business_saga_steps", {"id": step["id"], "state": "claimed"}, {
            "state": "completed", "completed_at": now, "claimed_by": None, "claimed_at": None,
            "updated_at": now, "output": output,
            "evidence": {**(step.get("evidence") or {}), "worker": worker, "effect": "internal_reversible_work_completed", "output_digest": _digest(output)},
        })
        _finish_saga(step["saga_id"])
        return {"status": "completed", "step_id": step["id"], "external_effect": False}
    result = _call_adapter(step, saga, agent)
    if result.get("ok"):
        receipt = result.get("receipt_digest") or _digest({"step": step["id"], "external_ref": result.get("external_ref"), "result": result})
        db.update("agentic_business_saga_steps", {"id": step["id"], "state": "claimed"}, {
            "state": "completed", "completed_at": now, "claimed_by": None, "claimed_at": None, "updated_at": now,
            "output": result, "evidence": {**(step.get("evidence") or {}), "approval_id": step.get("approval_id"), "receipt_digest": receipt, "worker": worker},
        })
        _finish_saga(step["saga_id"])
        return {"status": "completed", "step_id": step["id"], "external_effect": True, "receipt_digest": receipt}
    attempts = int(step.get("attempt_count") or 1)
    retry = bool(result.get("retryable")) and attempts < 5
    db.update("agentic_business_saga_steps", {"id": step["id"], "state": "claimed"}, {
        "state": "ready" if retry else "blocked", "claimed_by": None, "claimed_at": None, "updated_at": now,
        "evidence": {**(step.get("evidence") or {}), "last_error": result.get("error"), "adapter_configured": bool(_adapter_url(step.get("connector_provider")))},
    })
    if not retry:
        db.update("agentic_business_sagas", {"id": step["saga_id"]}, {"state": "blocked", "updated_at": now, "outcome": {"blocked_step": step["id"], "reason": result.get("error")}})
    return {"status": "retry" if retry else "blocked", "step_id": step["id"], "error": result.get("error")}


def predict_work(limit=200):
    now = datetime.datetime.now(datetime.timezone.utc)
    horizon = (now + datetime.timedelta(days=30)).isoformat()
    obligations = db.select("legal_obligations", {"select": "id,organization_id,contract_id,obligation,due_at,status", "status": "in.(open,due)", "due_at": f"lte.{horizon}", "limit": str(limit)}) or []
    financial = db.select("business_financial_events", {"select": "id,organization_id,event_type,amount,currency,status,occurred_at", "status": "in.(pending,attention)", "limit": str(limit)}) or []
    created = 0
    for item in obligations:
        row = {"organization_id": item["organization_id"], "agent_key": "treasury_chief" if any(x in str(item.get("obligation", "")).lower() for x in ("pay", "invoice")) else "legal_chief", "prediction_type": "obligation_window", "title": item.get("obligation") or "Upcoming obligation", "predicted_for": item.get("due_at"), "confidence": .9, "expected_value": {"attention_minutes_avoided": 30}, "evidence": {"obligation_id": item["id"], "contract_id": item.get("contract_id")}, "recommended_saga_type": "payment_run" if "pay" in str(item.get("obligation", "")).lower() else "contract_renewal"}
        row["prediction_digest"] = _digest(row)
        db.insert("predictive_business_work_items", row, upsert=True); created += 1
    for item in financial:
        row = {"organization_id": item["organization_id"], "agent_key": "accounting_controller", "prediction_type": "financial_exception", "title": f"Resolve {item.get('event_type', 'financial')} exception", "predicted_for": item.get("occurred_at"), "confidence": .85, "expected_value": {"amount": item.get("amount"), "currency": item.get("currency")}, "evidence": {"financial_event_id": item["id"]}, "recommended_saga_type": "monthly_close"}
        row["prediction_digest"] = _digest(row)
        db.insert("predictive_business_work_items", row, upsert=True); created += 1
    return {"predictions": created}


def run_once():
    return {"execution": execute_once(), "prediction": predict_work()}


if __name__ == "__main__":
    print(json.dumps(run_once(), default=str))
