"""Local REST dispatcher joining the compliance modules behind one safe API surface.

The gateway never submits filings or alters protected policies; it queues/proposes those
operations for the existing approval workflow.
"""
from __future__ import annotations
from dataclasses import asdict
from typing import Any

import compliance_auth
from app_isolation_engine import AppIsolationEngine
from compliance_event_stream import ComplianceEvent, ComplianceEventStream, ComplianceEventType
from compliance_knowledge_graph import ComplianceKnowledgeGraph
from evidence_collector import EvidenceCollector
from filing_optimizer_v2 import SmartFilingOptimizer
from anomaly_detector import CrossModuleAnomalyDetector
from dept_scorecard import DepartmentPerformanceScorecard
from simulation_sandbox import ComplianceSimulationSandbox
from auto_remediation_v2 import AutoRemediationEngineV2


class ComplianceAPIGateway:
    def __init__(self) -> None:
        self.isolation = AppIsolationEngine()
        self.events = ComplianceEventStream()
        self.graph = ComplianceKnowledgeGraph()
        self.evidence = EvidenceCollector()
        self.filings = SmartFilingOptimizer()
        self.anomalies = CrossModuleAnomalyDetector()
        self.scorecards = DepartmentPerformanceScorecard()
        self.simulations = ComplianceSimulationSandbox()
        self.remediation = AutoRemediationEngineV2()
        self.rate_limiter = compliance_auth.RateLimiter()
        self.events.subscribe(ComplianceEventType.REGULATION_INGESTED, self._index_regulation)

    def _index_regulation(self, event: ComplianceEvent) -> None:
        regulation = str(event.payload.get("regulation_id", event.event_id))
        for requirement in event.payload.get("requirements", []):
            self.graph.link(regulation, str(requirement), "requires")
            self.graph.link(str(requirement), f"app:{event.app_id}", "applies_to")

    def dispatch(self, method: str, path: str, body: dict[str, Any] | None = None,
                 principal: "compliance_auth.Principal | None" = None,
                 client_host: str | None = None,
                 token: str | None = None) -> tuple[int, dict[str, Any]]:
        """Route a compliance request under an authenticated principal.

        `principal` is resolved here when the caller did not already do it, so
        no transport can reach the handlers unauthenticated. Tenancy comes from
        the principal; `body["tenant_id"]` is only ever a *request*, checked
        against what the principal is allowed to touch.
        """
        body = body or {}; method = method.upper(); pieces = [x for x in path.split("?")[0].split("/") if x]
        if pieces[:2] != ["compliance", "v1"]:
            return 404, {"error": "unknown endpoint"}
        endpoint = pieces[2:]

        # Liveness answers before auth: a health probe must not need a
        # credential, and it exposes nothing tenant-specific.
        if method == "GET" and endpoint == ["health"]:
            return 200, {"status": "ok", "service": "compliance-api-gateway"}

        try:
            if principal is None:
                principal = compliance_auth.resolve_principal(token=token, client_host=client_host)
            self.rate_limiter.check(f"{principal.name}:{principal.tenant}")
        except compliance_auth.AuthError as exc:
            compliance_auth.audit(f"{method} {path}", principal, status=exc.status,
                                  detail=str(exc), client_host=client_host)
            return exc.status, {"error": str(exc)}

        try:
            # One tenant decision for the whole request, made from the
            # principal. Every handler below uses `tenant`, never the body.
            tenant = compliance_auth.authorize_tenant(principal, body.get("tenant_id"))
            write_needed = method in ("POST", "PUT", "PATCH", "DELETE")
            if write_needed:
                compliance_auth.require_scope(principal, compliance_auth.WRITE)
            else:
                compliance_auth.require_scope(principal, compliance_auth.READ)

            if method == "GET" and endpoint == ["readiness"]:
                try:
                    import compliance_periodic
                    snapshot = compliance_periodic.health()
                except Exception as exc:
                    return 200, {"status": "unknown", "error": str(exc)[:200]}
                snapshot["service"] = "compliance-api-gateway"
                return (503 if snapshot.get("status") == "degraded" else 200), snapshot
            if method == "GET" and len(endpoint) == 2 and endpoint[0] == "apps":
                result = 200, self.isolation.snapshot(tenant, endpoint[1])
                compliance_auth.audit(f"GET apps/{endpoint[1]}", principal, status=200)
                return result
            if method == "POST" and len(endpoint) == 3 and endpoint[0] == "apps" and endpoint[2] == "risk-score":
                old, new = self.isolation.set_risk_score(tenant, endpoint[1], body["score"])
                self.events.publish(ComplianceEvent(ComplianceEventType.RISK_SCORE_CHANGED, endpoint[1], {"old": old, "new": new}, tenant))
                compliance_auth.audit(f"POST apps/{endpoint[1]}/risk-score", principal,
                                      status=200, detail=f"{old}->{new}")
                return 200, {"old": old, "new": new}
            if method == "POST" and endpoint == ["events"]:
                event = ComplianceEvent(ComplianceEventType(body["kind"]), body["app_id"], body.get("payload", {}), tenant)
                published = asdict(self.events.publish(event))
                compliance_auth.audit("POST events", principal, status=202,
                                      detail=str(body.get("kind")))
                return 202, published
            if method == "GET" and endpoint == ["events"]:
                # Tenant-scoped: a caller must not read another tenant's stream.
                visible = [asdict(e) for e in self.events.recent(int(body.get("limit", 100)), body.get("app_id"))
                           if getattr(e, "tenant_id", tenant) == tenant]
                return 200, {"events": visible}
            if method == "POST" and endpoint == ["filings", "optimize"]:
                return 200, self.filings.optimize(body.get("filings", []))
            if method == "POST" and endpoint == ["graph", "link"]:
                return 201, asdict(self.graph.link(body["source"], body["target"], body["relation"], **body.get("metadata", {})))
            if method == "POST" and endpoint == ["graph", "path"]:
                return 200, {"path": [asdict(e) for e in self.graph.shortest_path(body["source"], body["target"])]}
            if method == "POST" and endpoint == ["evidence", "collect"]:
                return 201, self.evidence.collect(body["app_id"], body["kind"], body["subject"], file_path=body.get("file_path"), metadata=body.get("metadata"))
            if method == "POST" and endpoint == ["anomalies", "detect"]:
                value = self.anomalies.detect(body["metric"], body["values"], float(body.get("threshold", 3)))
                return 200, {"anomaly": asdict(value) if value else None}
            if method == "POST" and endpoint == ["departments", "scorecard"]:
                return 200, self.scorecards.score(**body)
            if method == "POST" and endpoint == ["simulations"]:
                snapshot, scenario = body.get("snapshot", {}), body.get("scenario", {})
                def pipeline(state, changes):
                    state.update(changes.get("state_patch", {}))
                    return {"projected_risk_score": max(0, min(100, float(state.get("risk_score", 0)) + float(changes.get("risk_delta", 0)))),
                            "projected_filing_count": len(state.get("filing_queue", [])) + int(changes.get("filing_delta", 0))}
                return 200, self.simulations.run(snapshot, scenario, pipeline)
            if method == "POST" and endpoint == ["remediations", "propose"]:
                issue = body.get("issue", {})
                plan = body.get("plan", {"operation": "review"})
                result = self.remediation.propose(body.get("app_id", "unknown"), issue, plan)
                return 200, asdict(result)
            return 404, {"error": "unknown endpoint"}
        except compliance_auth.AuthError as exc:
            # Authorization failures are audited with the attempted action, so
            # a cross-tenant probe leaves a trail rather than a 403 and silence.
            compliance_auth.audit(f"{method} {path}", principal, status=exc.status,
                                  detail=str(exc),
                                  requested_tenant=str(body.get("tenant_id") or ""))
            return exc.status, {"error": str(exc)}
        except (KeyError, TypeError, ValueError) as exc:
            compliance_auth.audit(f"{method} {path}", principal, status=400, detail=str(exc))
            return 400, {"error": str(exc)}


gateway = ComplianceAPIGateway()
